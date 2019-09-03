#!/usr/bin/env python3
import os

from pprint import pprint, pformat

from flask import Flask, request, url_for, redirect
import spotipy
import spotipy.util
from spotipy.oauth2 import SpotifyOAuth
from redis import StrictRedis
from redis_collections import Dict


app = Flask(__name__)


SCOPE = "user-read-currently-playing playlist-modify-private " \
        "user-read-playback-state playlist-modify-public " \
        "playlist-read-private user-library-read user-library-modify"


@app.route('/')
def index():
    username = request.args.get('username')
    if not username:
        return redirect(url_for('login'))
    spotify = get_spotify(username)

    now_playing = spotify.currently_playing()
    if not now_playing or not now_playing.get('is_playing', False):
        return "Nothing playing."

    title = f"{now_playing['item']['artists'][0]['name']} - {now_playing['item']['name']}"
    href = now_playing['item'].get('external_urls', {}).get('spotify')
    if href:
        return f"""<a href="{href}">{title}</a>"""


@app.route('/login')
def login():
    r = get_redirect()
    oauth = get_oauth()
    if r:
        oauth.redirect_uri += f"?r={r}"
    auth_url = oauth.get_authorize_url()
    return redirect(auth_url)


@app.route('/login_result')
def login_result():
    code = request.args.get("code")
    if not code:
        return "Not found", 404
    r = get_redirect()
    oauth = get_oauth()
    if r:
        oauth.redirect_uri += f"?r={r}"
    token_info = oauth.get_access_token(code)
    sp = spotipy.Spotify(token_info['access_token'])
    username = sp.me()['id']
    oauth.username = username
    oauth._add_custom_values_to_token_info(token_info)
    oauth._save_token_info(token_info)
    view = r if r else 'index'
    return redirect(url_for(view) + f"?username={username}")


@app.route('/save')
def save():
    username = request.args.get('username')
    if not username:
        return redirect(url_for('login') + "?r=save")
    spotify = get_spotify(username)

    now_playing = spotify.currently_playing()
    if not now_playing or not now_playing.get('is_playing', False):
        return "Nothing playing."

    item_id = now_playing['item']['id']

    try:
        actions = ""
        if not spotify.current_user_saved_tracks_contains([item_id])[0]:
            spotify.current_user_saved_tracks_add([item_id])
            actions += "❤️"

        playlist_id = os.environ['SPOTIFY_PLAYLIST']
        if not playlist_contains_track(spotify, username, playlist_id, item_id):
            spotify.user_playlist_add_tracks(username, playlist_id, [item_id])
            actions += "☑️"
    except spotipy.SpotifyException:
        return redirect(url_for("login") + "?r=save")

    title = f"{now_playing['item']['artists'][0]['name']} - {now_playing['item']['name']}"
    href = now_playing['item'].get('external_urls', {}).get('spotify')
    if href:
        return f"""{actions}{' ' if actions else ''}<a href="{href}">{title}</a>"""



def playlist_contains_track(spotify, username, playlist_id, track_id):
    def track_present(items):
        return any((t['track']['id'] == track_id for t in items))

    results = spotify.user_playlist(username, playlist_id, fields="tracks(items(track(id)),next)")['tracks']

    if track_present(results['items']):
        return True

    while results['next']:
        results = spotify.next(results)
        if track_present(results['items']):
            return True

    return False


def get_spotify(username):
    token = get_token(username)
    return spotipy.Spotify(token)


def get_token(username):
    oauth = get_oauth(username)
    token_info = oauth.get_cached_token()
    if token_info:
        return token_info['access_token']

def get_oauth(username=None):
    client_id = os.getenv('SPOTIPY_CLIENT_ID')
    client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
    redirect_uri = url_for("login_result", _external=True, _scheme="https")
    return SpotifyOAuthRedis(client_id, client_secret, redirect_uri, scope=SCOPE, username=username)


def get_redirect():
    r = request.args.get('r')
    return r if r in {'save'} else None


_redis_connection = None
def get_redis():
    global _redis_connection
    if not _redis_connection:
        _redis_connection = StrictRedis(
            host=os.environ['REDIS_HOST'],
            port=int(os.environ['REDIS_PORT']),
            db=int(os.environ['REDIS_DB']),
            password=os.environ['REDIS_PASSWORD'],
        )
    return _redis_connection

class SpotifyOAuthRedis(SpotifyOAuth):
    redis_key = "spotifytokens"
    username = None

    def __init__(self, *args, **kwargs):
        username = kwargs.pop('username')
        super().__init__(*args, **kwargs)
        self.username = username

    def _save_token_info(self, token_info):
        if self.username:
            Dict(key=self.redis_key, redis=get_redis())[self.username] = token_info

    def get_cached_token(self):
        if self.username:
            token_info = Dict(key=self.redis_key, redis=get_redis()).get(self.username)
            if token_info and self.is_token_expired(token_info):
                token_info = self.refresh_access_token(token_info['refresh_token'])
            return token_info

    def _add_custom_values_to_token_info(self, token_info):
        token_info['username'] = self.username
        return super()._add_custom_values_to_token_info(token_info)
