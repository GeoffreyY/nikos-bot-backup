"""using my account (iceman1415) as backup twitch bot for nikosstudio
to create a songlist
and provide misc. functions while we're here"""
import sys
from math import ceil

from datetime import datetime
from time import sleep

import hashlib

import irc.bot
import requests

from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file as oafile, client as oaclient, tools as oatools

import spotipy
import spotipy.util as sputil

# how long to wait before posting in chat again
WAIT_TIME = 0.8

# stuff to access spotify
SPOTIPY_CLIENT_ID = open('spotify/clientid', 'r').read()
SPOTIPY_CLIENT_SECRET = open('spotify/secret', 'r').read()
SPOTIPY_REDIRECT_URI = 'http://localhost'

SPOTIFY_USERNAME = 'geoffreyy1415'
SPOTIFY_SCOPE = 'user-library-read'

# stuff to access google spreadsheed
SPREADSHEET_ID = '1-uwntIJDqMCnOUmvomK-5EqUnzHup2rABLBbhcotmZM'
SPREADSHEET_SCOPES = 'https://www.googleapis.com/auth/spreadsheets'
SPREADSHEET_CREDENTIALS_FILE = 'google/credentials.json'
SPREADSHEET_SECRETS_FILE = 'google/client_secret.json'

SONGLIST_URL = 'https://docs.google.com/spreadsheets/d/' + SPREADSHEET_ID
SONGLIST_URL_SHORT = 'https://goo.gl/bwxXAW'

SPREADSHEET_STORE = oafile.Storage(SPREADSHEET_CREDENTIALS_FILE)
SPREADSHEET_CREDS = SPREADSHEET_STORE.get()
if not SPREADSHEET_CREDS or SPREADSHEET_CREDS.invalid:
    FLOW = oaclient.flow_from_clientsecrets(
        SPREADSHEET_SECRETS_FILE, SPREADSHEET_SCOPES)
    SPREADSHEET_CREDS = oatools.run_flow(FLOW, SPREADSHEET_STORE)
SPREADSHEET = build(
    'sheets', 'v4', http=SPREADSHEET_CREDS.authorize(Http()))

SHEET_ID = 25658793  # id of 'Songlist' sheet
BACKUP_SHEET_ID = 766377016  # id of 'datadump' sheet

# cooldown between deleting rows in spreadsheet
# in case multiple ppl request it at the same time
# TODO: better method than using global variable?
delete_wait = 5
time_old = datetime.utcnow()
print(time_old)


def add_song(song, artist, requested_by, duration, url):
    """append song entry to the spreadsheet"""

    time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    # hash to uniquely identify the song entry
    hashing = url + requested_by + time
    hash_str = hashlib.md5(hashing.encode('utf-8')).hexdigest()

    song_body = {'values': [
        [song, artist, requested_by, duration, url, time, hash_str]]}

    # add to current song list
    result1 = SPREADSHEET.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range='Songlist!A2:G',
        valueInputOption='USER_ENTERED', body=song_body).execute()
    # and also permanent song list
    result2 = SPREADSHEET.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range='datadump!A2:G',
        valueInputOption='USER_ENTERED', body=song_body).execute()

    # error logging
    open('log/reply.txt', 'a').write(str(result1)+'\n')
    open('log/reply.txt', 'a').write(str(result2)+'\n')
    print('added song ' + song)


def delete_rows_raw(start, end):
    """delete rows from the spreadsheet"""

    delete_row_body = {"requests": [{"deleteDimension": {
        "range": {
            "sheetId": SHEET_ID,
            "dimension": "ROWS",
            "startIndex": start,
            "endIndex": end
        }
    }}, ], }
    result = SPREADSHEET.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body=delete_row_body).execute()

    # error logging
    open('log/reply.txt', 'a').write(str(result)+'\n')
    print('deleted rows from ' + str(start) + '..' + str(end))


def delete_rows(start, end):
    """check if there's any problems before actually deleting"""

    # can't delete negative rows
    if end < start:
        print('deleting end row lower than start row')
        # this shouldn't happen
        raise ValueError('end less than start')

    # don't delete if recently deleted rows already
    global time_old
    time_now = datetime.utcnow()
    time_diff = time_now - time_old
    if time_diff.seconds < delete_wait:
        print('waiting ' + str(delete_wait - time_diff.seconds) + ' more seconds...')
        return False

    delete_rows_raw(start, end)
    time_old = time_now
    return True


def get_duration(milliseconds):
    """convert song duration, queried from spotify,
    from milliseconds to a 'min:sec' fromat string"""

    seconds = ceil(milliseconds / 1000)
    (minute, second) = divmod(seconds, 60)
    sec_str = str(second)
    while len(sec_str) < 2:
        sec_str = '0' + sec_str
    return str(minute) + ':' + sec_str


def num_suffix(num):
    """get suffix for a number
    e.g. 'st' for 101, 'nd' for 102, 'th' for 104"""

    last_digits = num % 100
    if last_digits in [11, 12, 13]:
        return 'th'
    if last_digits % 10 == 1:
        return 'st'
    if last_digits % 10 == 2:
        return 'nd'
    if last_digits % 10 == 3:
        return 'rd'
    return 'th'


def has_power(message_full):
    """check if user has power to use advance commands"""

    whitelist = open('whitelist', 'r').read().split('\n')

    tags = message_full.tags
    for item in tags:
        if item['key'] == 'display-name':
            name = item['value']
            if name in whitelist:
                return True
        elif item['key'] == 'badges':
            if 'moderator' in item['value'] or 'broadcaster' in item['value']:
                return True

    return False


def log_message(message):
    """logging all comments, why not"""

    # also logging with time stamp
    time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    author = message.source.split('!')[0]
    comment = message.arguments[0]
    log = time + ' ' + author + ': ' + comment
    open("log/comment_log.txt", "a").write(log + '\n')
    print(author + ': ' + message)


class TwitchBot(irc.bot.SingleServerIRCBot):
    """The twitch bot"""

    def __init__(self, username, client_id, token, channel):
        self.client_id = client_id
        self.token = token
        self.channel = '#' + channel

        # Get the channel id, we will need this for twitch v5 API calls
        url = 'https://api.twitch.tv/kraken/users?login=' + channel
        headers = {'Client-ID': client_id,
                   'Accept': 'application/vnd.twitchtv.v5+json'}
        result = requests.get(url, headers=headers).json()
        # print(r)
        self.channel_id = result['users'][0]['_id']

        # Create IRC bot connection
        server = 'irc.chat.twitch.tv'
        port = 6667
        print('Connecting to ' + server + ' on port ' + str(port) + '...')
        irc.bot.SingleServerIRCBot.__init__(
            self, [(server, port, 'oauth:'+token)], username, username)

    def on_welcome(self, c, e):
        """no idea what this function does or how it's called"""

        print('Joining ' + self.channel)

        # request specific capabilities, whatever these are
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')

        c.join(self.channel)

        # set timer after joining
        global time_old
        time_old = datetime.utcnow()

    def on_pubmsg(self, c, e):
        """parsing messages"""

        author = e.source.split('!')[0]
        message = e.arguments[0]

        # logging
        log_message(e)

        shadowing = ['nikos_bot', 'iceman1415']
        if author.lower() in shadowing:
            self.shadow(message)

        # If a chat message starts with an exclamation point, try to run it as a command
        if e.arguments[0][:1] == '!':
            cmd = e.arguments[0].split(' ')[0][1:]
            # logging
            print('Received command: ' + cmd)
            self.do_command(e, cmd, e.arguments[0].split(' ')[1:])
        return

    def do_command(self, e, cmd, args):
        """execute commands when prompted
        '![cmd] [args]'"""

        # sleep a bit to wait for chat cooldown
        # so I can activate my own commands
        # TODO: this maybe also sleeping the bot (stop parsing comments)
        # so see if there's a better way
        if e.source.split('!')[0] == 'Iceman1415':
            sleep(WAIT_TIME)

        conn = self.connection
        cmd = cmd.lower()
        cmd.replace('_', '')

        '''
        # provided example from twith
        # Poll the API the get the current status of the stream
        elif cmd == "title":
            url = 'https://api.twitch.tv/kraken/channels/' + self.channel_id
            headers = {'Client-ID': self.client_id,
                       'Accept': 'application/vnd.twitchtv.v5+json'}
            r = requests.get(url, headers=headers).json()
            c.privmsg(self.channel, r['display_name'] +
                      ' channel title is currently ' + r['status'])'''

        # provide song list link
        if cmd in ['songlist', 'sl']:
            message = "nikos' internet is too bad to update his spreadsheet... " + \
                SONGLIST_URL_SHORT + ' <-- try this one!'
            conn.privmsg(self.channel, message)

        # provide full link to song list spreadsheet
        elif cmd == 'songlistfull':
            conn.privmsg(self.channel, SONGLIST_URL)

        # delete first few rows of songlist
        # requires admin power
        elif cmd in ['deleterows', 'delete']:
            if not has_power(e):
                message = 'this command needs admin privilages :/'
                conn.privmsg(self.channel, message)
            else:
                # see if we're deleting multiple rows
                try:
                    row_num = int(args[0])
                except:
                    row_num = 1

                if delete_rows(1, row_num+1):
                    message = 'deleted ' + str(row_num) + ' rows'
                    conn.privmsg(self.channel, message)

        # delete songs from songlist
        # requires admin power
        elif cmd in ['deleteupto', 'isplaying']:
            if not has_power(e):
                message = 'this command needs admin privilages :/'
                conn.privmsg(self.channel, message)
            elif not args:
                message = 'please specify which song to delete up to (using hash)'
                conn.privmsg(self.channel, message)
            else:
                given_hash = args[0]
                hash_length = len(given_hash)
                result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                                 range='SongList!G2:G').execute()
                # find the last song with the given hash
                row_num = -1
                for (i, entry) in reversed(list(enumerate(result['values']))):
                    print(str(entry)+'/')
                    print(given_hash+'/')
                    if len(entry) != 1:
                        pass
                    elif (entry[0][:hash_length] == given_hash or
                          entry[0][-hash_length:] == given_hash):
                        row_num = i

                if row_num == -1:
                    message = 'can\'t find song with given hash'
                    conn.privmsg(self.channel, message)
                else:
                    if delete_rows(1, row_num+1):
                        message = 'deleted ' + str(row_num) + ' rows'
                        conn.privmsg(self.channel, message)

        # request smash mouth
        elif cmd == 'sm':
            message = '!sr smash mouth'
            conn.privmsg(self.channel, message)

        # ping bot
        elif cmd == 'test':
            message = 'test'
            conn.privmsg(self.channel, message)

        # remove smash mouth
        elif cmd == 'notsmashmouthagainplease':
            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='SongList!B2:C').execute()
            # check if my last song request is smash mouth
            found = False
            for entry in result['values']:
                if result[1].strip() == 'iceman1415':
                    if result[0].strip().lower() == 'smash mouth':
                        found = True
                    else:
                        found = False

            if found:
                message = '!wrongsong'
                conn.privmsg(self.channel, message)
            else:
                message = 'last song requested by me isn\'t smash mouth...'
                conn.privmsg(self.channel, message)

        # link to this code
        elif cmd == 'code':
            github_link = 'https://github.com/GeoffreyY/nikos-bot-backup'
            conn.privmsg(self.channel, github_link)

        # stupid command
        elif cmd == 'bot':
            message = 'MrDestructoid beep boop MrDestructoid'
            conn.privmsg(self.channel, message)

        # check length of remaning songs
        elif cmd == 'timeremain':
            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='SongList!F2:F').execute()
            # add up the durations of the songs
            (minute, second) = (0, 0)
            for time_str in result['values']:
                (tmp_min, tmp_sec) = (int(time_str[:-3]), int(time_str[-2:]))
                minute += tmp_min
                second += tmp_sec
                while second > 60:
                    second -= 60
                    minute += 1

            message = str(minute) + ':' + str(second) + \
                ' worth of songs remaining'
            conn.privmsg(self.channel, message)

    def shadow(self, message):
        """respond when nikos_bot acts"""

        # add song to spreadsheet when nikos_bot added song
        # eg: 'Iceman1415 --> The song Smash Mouth - All Star has been added to the queue.'
        if message[-29:] == ' has been added to the queue.':
            # parse nikos_bot's comment
            pos = message.find(' --> The song ')
            requested_by = message[:pos]
            song = message[pos+14:-29].split(' - ')

            # generate a new spotify token for every query
            sp_token = sputil.prompt_for_user_token(SPOTIFY_USERNAME, SPOTIFY_SCOPE,
                                                    client_id=SPOTIPY_CLIENT_ID,
                                                    client_secret=SPOTIPY_CLIENT_SECRET,
                                                    redirect_uri=SPOTIPY_REDIRECT_URI)
            sp = spotipy.Spotify(auth=sp_token)
            sp_search_results = sp.search(q=' '.join(song), limit=1)

            # parse search result
            sp_song = sp_search_results['tracks']['items'][0]
            sp_url = sp_song['external_urls']['spotify']
            song_duration = get_duration(sp_song['duration_ms'])

            # add song to song list
            add_song(' '.join(song[1:]), song[0],
                     requested_by, song_duration, sp_url)

        # remove song from spreadsheet when nikos_bot removed song
        # eg: 'Lotusf198, Successfully removed your song!'
        elif message[-33:] == ', Successfully removed your song!':
            remover = message[:-33]
            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='SongList!C2:C').execute()

            # find the location of song to remove
            found = False
            for i, entry in enumerate(result['values']):
                if entry[0].strip() == remover:
                    row = i
                    found = True

            if not found:
                print("Error: no entry listed by " + remover)
            else:
                delete_rows_raw(row+1, row+2)

        # eg: 'Current song: Avenged Sevenfold - Hail to the King Requested by Luna_Eclipse0'
        elif message[:14] == 'Current song: ':
            pos = message.rfind(' Requested by ')
            song_full = message[14:pos].split(' - ')
            artist = song_full[0]
            song = ' '.join(song_full[1:])
            requested_by = message[pos+14:]

            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='SongList!A2:C').execute()

            # find 'current song' from song list
            found = False
            for i, entry in enumerate(result['values']):
                if (entry[0].strip() == song and entry[1].strip() == artist and
                        entry[2].strip() == requested_by):
                    row = i
                    found = True

            if not found:
                print('Error: no entry listed as ' + song +
                      ' by ' + artist + ' from ' + requested_by)
            else:
                delete_rows_raw(1, row+1)


def main():
    """main"""
    if len(sys.argv) != 5:
        print("Usage: twitchbot <username> <client id> <token> <channel>")
        sys.exit(1)

    username = sys.argv[1]
    client_id = sys.argv[2]
    token = sys.argv[3]
    channel = sys.argv[4]

    bot = TwitchBot(username, client_id, token, channel)
    bot.start()


if __name__ == "__main__":
    main()
