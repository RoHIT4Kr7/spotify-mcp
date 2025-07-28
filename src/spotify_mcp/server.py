import asyncio
import base64
import os
import logging
import sys
from enum import Enum
import json
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import mcp.types as types
from mcp.server import NotificationOptions, Server
from pydantic import BaseModel, Field, AnyUrl
from spotipy import SpotifyException
from fastmcp import FastMCP

from . import spotify_api
from .utils import normalize_redirect_uri

# Configuration
MY_NUMBER = "919608765599"  # Replace with your actual number


def setup_logger():
    class Logger:
        def info(self, message):
            print(f"[INFO] {message}", file=sys.stderr)

        def error(self, message):
            print(f"[ERROR] {message}", file=sys.stderr)

    return Logger()


logger = setup_logger()

# Normalize the redirect URI to meet Spotify's requirements
if spotify_api.REDIRECT_URI:
    spotify_api.REDIRECT_URI = normalize_redirect_uri(spotify_api.REDIRECT_URI)
spotify_client = spotify_api.Client(logger)

# Create FastMCP instance
mcp = FastMCP("spotify-mcp")


class ToolModel(BaseModel):
    @classmethod
    def as_tool(cls):
        return types.Tool(
            name="Spotify" + cls.__name__,
            description=cls.__doc__,
            inputSchema=cls.model_json_schema(),
        )


class Validate(ToolModel):
    """Validate tool that returns the stored number for WhatsApp client verification."""

    pass


class Playback(ToolModel):
    """Manages the current playback with the following actions:
    - get: Get information about user's current track.
    - start: Starts playing new item or resumes current playback if called with no uri.
    - pause: Pauses current playback.
    - skip: Skips current track.
    """

    action: str = Field(
        description="Action to perform: 'get', 'start', 'pause' or 'skip'."
    )
    spotify_uri: Optional[str] = Field(
        default=None,
        description="Spotify uri of item to play for 'start' action. "
        + "If omitted, resumes current playback.",
    )
    num_skips: Optional[int] = Field(
        default=1, description="Number of tracks to skip for `skip` action."
    )


class Queue(ToolModel):
    """Manage the playback queue - get the queue or add tracks."""

    action: str = Field(description="Action to perform: 'add' or 'get'.")
    track_id: Optional[str] = Field(
        default=None, description="Track ID to add to queue (required for add action)"
    )


class GetInfo(ToolModel):
    """Get detailed information about a Spotify item (track, album, artist, or playlist)."""

    item_uri: str = Field(
        description="URI of the item to get information about. "
        + "If 'playlist' or 'album', returns its tracks. "
        + "If 'artist', returns albums and top tracks."
    )


class Search(ToolModel):
    """Search for tracks, albums, artists, or playlists on Spotify."""

    query: str = Field(description="query term")
    qtype: Optional[str] = Field(
        default="track",
        description="Type of items to search for (track, album, artist, playlist, "
        + "or comma-separated combination)",
    )
    limit: Optional[int] = Field(
        default=10, description="Maximum number of items to return"
    )


class Playlist(ToolModel):
    """Manage Spotify playlists.
    - get: Get a list of user's playlists.
    - get_tracks: Get tracks in a specific playlist.
    - add_tracks: Add tracks to a specific playlist.
    - remove_tracks: Remove tracks from a specific playlist.
    - change_details: Change details of a specific playlist.
    """

    action: str = Field(
        description="Action to perform: 'get', 'get_tracks', 'add_tracks', 'remove_tracks', 'change_details'."
    )
    playlist_id: Optional[str] = Field(
        default=None, description="ID of the playlist to manage."
    )
    track_ids: Optional[List[str]] = Field(
        default=None, description="List of track IDs to add/remove."
    )
    name: Optional[str] = Field(default=None, description="New name for the playlist.")
    description: Optional[str] = Field(
        default=None, description="New description for the playlist."
    )


@mcp.tool()
async def validate() -> str:
    """
    NOTE: This tool must be present in an MCP server used by puch.
    """

    return MY_NUMBER


@mcp.tool()
def SpotifyPlayback(
    action: str, spotify_uri: Optional[str] = None, num_skips: Optional[int] = 1
) -> str:
    """Manages Spotify playback including getting current track info, starting/pausing playback, and skipping tracks.

    Use when: You need to control or get information about the user's current Spotify playback state.
    Side effects: May start, pause, or skip tracks on the user's active Spotify device.
    """
    """Manages the current playback with the following actions:
    - get: Get information about user's current track.
    - start: Starts playing new item or resumes current playback if called with no uri.
    - pause: Pauses current playback.
    - skip: Skips current track.
    """
    logger.info(
        f"Playback action: {action} with arguments: spotify_uri={spotify_uri}, num_skips={num_skips}"
    )

    try:
        match action:
            case "get":
                logger.info("Attempting to get current track")
                curr_track = spotify_client.get_current_track()
                if curr_track:
                    logger.info(
                        f"Current track retrieved: {curr_track.get('name', 'Unknown')}"
                    )
                    return json.dumps(curr_track, indent=2)
                logger.info("No track currently playing")
                return "No track playing."

            case "start":
                logger.info(f"Starting playback with spotify_uri: {spotify_uri}")
                spotify_client.start_playback(spotify_uri=spotify_uri)
                logger.info("Playback started successfully")
                return "Playback starting."

            case "pause":
                logger.info("Attempting to pause playback")
                spotify_client.pause_playback()
                logger.info("Playback paused successfully")
                return "Playback paused."

            case "skip":
                num_skips = int(num_skips or 1)
                logger.info(f"Skipping {num_skips} tracks.")
                spotify_client.skip_track(n=num_skips)
                return "Skipped to next track."

            case _:
                return f"Unknown action: {action}. Supported actions are: get, start, pause, skip."

    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return f"An error occurred with the Spotify Client: {str(se)}"
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return error_msg


@mcp.tool()
def SpotifySearch(
    query: str, qtype: Optional[str] = "track", limit: Optional[int] = 10
) -> str:
    """Search for tracks, albums, artists, or playlists on Spotify using text queries.

    Use when: You need to find specific music content on Spotify by name, artist, or other search terms.
    Side effects: None
    """
    """Search for tracks, albums, artists, or playlists on Spotify."""
    logger.info(f"Performing search with query: {query}, type: {qtype}, limit: {limit}")

    try:
        search_results = spotify_client.search(
            query=query,
            qtype=qtype or "track",
            limit=limit or 10,
        )
        logger.info("Search completed successfully.")
        return json.dumps(search_results, indent=2)

    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return f"An error occurred with the Spotify Client: {str(se)}"
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return error_msg


@mcp.tool()
def SpotifyQueue(action: str, track_id: Optional[str] = None) -> str:
    """Manage the Spotify playback queue by viewing current queue or adding tracks to it.

    Use when: You need to see what's coming up next in playback or add tracks to the queue.
    Side effects: Adding tracks will modify the user's playback queue.
    """
    """Manage the playback queue - get the queue or add tracks."""
    logger.info(f"Queue operation with action: {action}, track_id: {track_id}")

    try:
        match action:
            case "add":
                if not track_id:
                    logger.error("track_id is required for add to queue.")
                    return "track_id is required for add action"
                spotify_client.add_to_queue(track_id)
                return "Track added to queue."

            case "get":
                queue = spotify_client.get_queue()
                return json.dumps(queue, indent=2)

            case _:
                return f"Unknown queue action: {action}. Supported actions are: add and get."

    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return f"An error occurred with the Spotify Client: {str(se)}"
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return error_msg


@mcp.tool()
def SpotifyGetInfo(item_uri: str) -> str:
    """Get detailed information about a specific Spotify item (track, album, artist, or playlist) using its URI.

    Use when: You need comprehensive details about a specific Spotify item including metadata, tracks, or related information.
    Side effects: None
    """
    """Get detailed information about a Spotify item (track, album, artist, or playlist)."""
    logger.info(f"Getting item info for uri: {item_uri}")

    try:
        item_info = spotify_client.get_info(item_uri=item_uri)
        return json.dumps(item_info, indent=2)

    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return f"An error occurred with the Spotify Client: {str(se)}"
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return error_msg


@mcp.tool()
def SpotifyPlaylist(
    action: str,
    playlist_id: Optional[str] = None,
    track_ids: Optional[List[str]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Manage Spotify playlists including viewing user playlists, getting playlist tracks, adding/removing tracks, and modifying playlist details.

    Use when: You need to interact with the user's playlists - viewing, modifying, or managing playlist content.
    Side effects: May modify playlist contents, names, or descriptions depending on the action performed.
    """
    """Manage Spotify playlists.
    - get: Get a list of user's playlists.
    - get_tracks: Get tracks in a specific playlist.
    - add_tracks: Add tracks to a specific playlist.
    - remove_tracks: Remove tracks from a specific playlist.
    - change_details: Change details of a specific playlist.
    """
    logger.info(f"Playlist operation with action: {action}")

    try:
        match action:
            case "get":
                logger.info("Getting current user's playlists")
                playlists = spotify_client.get_current_user_playlists()
                return json.dumps(playlists, indent=2)

            case "get_tracks":
                if not playlist_id:
                    logger.error("playlist_id is required for get_tracks action.")
                    return "playlist_id is required for get_tracks action."
                logger.info(f"Getting tracks in playlist: {playlist_id}")
                tracks = spotify_client.get_playlist_tracks(playlist_id)
                return json.dumps(tracks, indent=2)

            case "add_tracks":
                if not playlist_id or not track_ids:
                    return (
                        "playlist_id and track_ids are required for add_tracks action."
                    )
                logger.info(f"Adding tracks to playlist: {playlist_id}")
                if isinstance(track_ids, str):
                    try:
                        track_ids = json.loads(track_ids)
                    except json.JSONDecodeError:
                        return "Error: track_ids must be a list or a valid JSON array."

                spotify_client.add_tracks_to_playlist(
                    playlist_id=playlist_id,
                    track_ids=track_ids,
                )
                return "Tracks added to playlist."

            case "remove_tracks":
                if not playlist_id or not track_ids:
                    return "playlist_id and track_ids are required for remove_tracks action."
                logger.info(f"Removing tracks from playlist: {playlist_id}")
                if isinstance(track_ids, str):
                    try:
                        track_ids = json.loads(track_ids)
                    except json.JSONDecodeError:
                        return "Error: track_ids must be a list or a valid JSON array."

                spotify_client.remove_tracks_from_playlist(
                    playlist_id=playlist_id,
                    track_ids=track_ids,
                )
                return "Tracks removed from playlist."

            case "change_details":
                if not playlist_id:
                    return "playlist_id is required for change_details action."
                if not name and not description:
                    return "At least one of name or description is required."

                logger.info(f"Changing playlist details for: {playlist_id}")
                spotify_client.change_playlist_details(
                    playlist_id=playlist_id,
                    name=name,
                    description=description,
                )
                return "Playlist details changed."

            case _:
                return f"Unknown playlist action: {action}. Supported actions are: get, get_tracks, add_tracks, remove_tracks, change_details."

    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return f"An error occurred with the Spotify Client: {str(se)}"
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return error_msg


async def main():
    """Main function to run the server with streamable HTTP transport."""
    logger.info("Starting Spotify MCP Server with Streamable HTTP transport")

    await mcp.run_async(
        "streamable-http",
        host="127.0.0.1",  # Allow external connections for ngrok
        port=int(os.environ.get("PORT", 8080)),
    )


if __name__ == "__main__":
    asyncio.run(main())
