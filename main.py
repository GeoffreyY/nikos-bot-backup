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
DELETE_WAIT = 5
TIME_OLD = datetime.utcnow()

# helper functions
##################


def get_duration(milliseconds):
    """converts song duration, queried from spotify,
    from milliseconds to a 'min:sec' fromat string"""

    seconds = ceil(milliseconds / 1000)
    (minute, second) = divmod(seconds, 60)
    sec_str = str(second)
    while len(sec_str) < 2:
        sec_str = '0' + sec_str
    return str(minute) + ':' + sec_str


def num_suffix(num):
    """gets suffix for the number
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
    """checks if user has power to use advance commands"""

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
    """logging all comments"""

    # logs with time stamp
    time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    author = message.source.split('!')[0]
    comment = message.arguments[0]
    log = time + ' ' + author + ': ' + comment
    open("log/comment_log.txt", "a").write(log + '\n')
    print(author + ': ' + comment)


def sum_time(time_vec):
    """sums over 'min:sec' strings, returns 'min:sec' string"""

    (minute, second) = (0, 0)
    for time_str in time_vec:
        if not time_str:
            continue
        (tmp_min, tmp_sec) = (int(time_str[:-3]), int(time_str[-2:]))
        minute += tmp_min
        second += tmp_sec

    while second > 60:
        second -= 60
        minute += 1

    second_str = str(second)
    while len(second_str) < 2:
        second_str = '0' + second_str

    return str(minute) + ':' + second_str

# twitch bot object
###################


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

    def on_welcome(self, connection, message):
        """no idea what this function does or how it's called"""

        # request specific capabilities, whatever these are
        connection.cap('REQ', ':twitch.tv/membership')
        connection.cap('REQ', ':twitch.tv/tags')
        connection.cap('REQ', ':twitch.tv/commands')

        print('Joining ' + self.channel)
        connection.join(self.channel)

        # set timer after joining
        global TIME_OLD
        TIME_OLD = datetime.utcnow()

    def on_pubmsg(self, connection, message):
        """parses messages"""

        author = message.source.split('!')[0].lower()
        comment = message.arguments[0]

        # logging
        log_message(message)

        shadowing = ['nikos_bot', 'iceman1415']
        if author in shadowing:
            shadow(comment)

        # If a chat comment starts with an exclamation point, try to run it as a command
        if comment[:1] == '!':
            cmd = comment.split(' ')[0][1:]
            self.do_command(message, author, cmd, comment.split(' ')[1:])

    def do_command(self, message, author, cmd, args):
        """executes commands when prompted
        '![cmd] [args]'"""

        # sleep and wait for chat cooldown to use my own commands
        # TODO: this maybe also sleeping the bot (stop parsing comments)
        # so see if there's a better way
        if author == 'iceman1415':
            print('sleeping...')
            sleep(WAIT_TIME)

        conn = self.connection
        cmd = cmd.lower().replace('_', '')

        print('Received command: ' + cmd)

        # provide song list link
        if cmd in ['songlist', 'sl']:
            comment = "nikos' internet is too bad to update his spreadsheet... " + \
                SONGLIST_URL_SHORT + ' <-- try this one!'
            conn.privmsg(self.channel, comment)

        # provide full link to song list spreadsheet
        elif cmd == 'songlistfull':
            conn.privmsg(self.channel, SONGLIST_URL)

        # delete first few rows of songlist, requires admin power
        elif cmd in ['deleterows', 'delete', 'del']:
            self.delete(message, args)

        elif cmd in ['restore', 'restores', 'restorefrom', 'restoresfrom']:
            self.restore(message, args)

        elif cmd == 'sm':
            conn.privmsg(self.channel, '!sr smash mouth')

        # remove smash mouth
        elif cmd == 'notsmashmouthagainplease':
            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='SongList!B2:C').execute()
            # check if my last song request is smash mouth
            for entry in reversed(result['values']):
                if entry[1] != 'Iceman1415':
                    continue
                elif entry[0].lower() == 'smash mouth':
                    conn.privmsg(self.channel, '!wrongsong')
                    break
                else:
                    comment = 'last song requested by me isn\'t smash mouth...'
                    conn.privmsg(self.channel, comment)
                    break

        elif cmd == 'code':
            github_link = 'https://github.com/GeoffreyY/nikos-bot-backup'
            conn.privmsg(self.channel, github_link)

        elif cmd == 'test':
            conn.privmsg(self.channel, 'test')

        elif cmd == 'bot':
            comment = 'MrDestructoid beep boop MrDestructoid I\'m still in beta'
            conn.privmsg(self.channel, comment)

        elif cmd == 'ping':
            conn.privmsg(self.channel, 'pong!')

        # check length of remaning songs
        elif cmd in ['timeleft', 'timeremaining', 'timeremain', 'remain']:
            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='SongList!D2:D').execute()
            # add up the durations of the songs
            total_duration = sum_time([x[0] for x in result['values']])

            comment = 'approx. ' + total_duration + \
                ' worth of songs remaining'
            conn.privmsg(self.channel, comment)

        elif cmd in ['commands', 'cmd', 'cmds']:
            comment = 'Partial list: !sl !sm !timeleft !code !ping'
            conn.privmsg(self.channel, comment)

        elif cmd in ['admin', 'admincommands', 'admincmd', 'admincmds']:
            comment = 'Admin commands: !delete !restore'
            conn.privmsg(self.channel, comment)

    def delete(self, message, args):
        """!delete [row_num = 1]
        deletes first [row_num] rows from song_list"""

        conn = self.connection

        if not has_power(message):
            comment = 'this command needs admin privilages :/'
            conn.privmsg(self.channel, comment)
        else:
            # see if we're deleting multiple rows
            if not args:
                row_num = 1
            else:
                try:
                    row_num = int(args[0])
                except ValueError:
                    row_num = 1

            if delete_rows(1, row_num+1):
                comment = 'deleted ' + str(row_num) + ' rows'
                conn.privmsg(self.channel, comment)

    def restore(self, message, args):
        """!restore <hash>
        restores songs to song list from datadump
        using given hash"""

        conn = self.connection

        if not args:
            comment = 'usage: !restore <hash>'
            conn.privmsg(self.channel, comment)
        elif not has_power(message):
            comment = 'this command needs admin privilages :/'
            conn.privmsg(self.channel, comment)
        else:
            old_row_data = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                                   range='Songlist!G2:G')
            old_hash = old_row_data.execute()['values'][0][0]

            result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                             range='datadump!G2:G').execute()

            old_row = -1
            new_row = -1
            for (i, entry) in reversed(list(enumerate(result['values']))):
                if not entry:
                    continue
                if entry[0] == old_hash:
                    old_row = i
                if entry[0] == args[0]:
                    new_row = i
                    break
            if old_row == -1 or new_row == -1:
                print('can\'t find song with provided hash')
                return
            row_diff = old_row - new_row

            get_data_range = 'datadump!A' + \
                str(new_row + 1) + ':G' + str(old_row)
            restore_data = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                                   range=get_data_range).execute()

            insert_row_body = {"requests": [{"insertDimension": {
                "range": {
                    "sheetId": SHEET_ID,
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": 1 + row_diff
                },
                "inheritFromBefore": False
            }}, ], }
            result = SPREADSHEET.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID, body=insert_row_body).execute()

            open('log/reply.txt', 'a').write(str(result)+'\n')

            paste_range = 'Songlist!A2:G' + str(row_diff + 1)
            restore_body = {'range': paste_range,
                            'majorDimension': 'ROWS',
                            'values': restore_data['values']}
            request = SPREADSHEET.spreadsheets().values().update(spreadsheetId=SPREADSHEET_ID,
                                                                 range=paste_range,
                                                                 valueInputOption='USER_ENTERED',
                                                                 body=restore_body)
            result = request.execute()

            open('log/reply.txt', 'a').write(str(result)+'\n')


# core functions
################


def add_song(song, artist, requested_by, duration, url):
    """appends song entry to the spreadsheet"""

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
    """deletes rows from the spreadsheet"""

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
    print('deleted rows from ' + str(start+1) + '..' + str(end+1))


def delete_rows(start, end):
    """checks if there's any problems before actually deleting"""

    # can't delete negative rows
    if end < start:
        print('deleting end row lower than start row')
        # this shouldn't happen
        raise ValueError('end less than start')

    # don't delete if recently deleted rows already
    global TIME_OLD
    time_now = datetime.utcnow()
    time_diff = time_now - TIME_OLD
    if time_diff.seconds < DELETE_WAIT:
        print('waiting ' + str(DELETE_WAIT - time_diff.seconds) + ' more seconds...')
        return False

    delete_rows_raw(start, end)
    TIME_OLD = time_now
    return True


def delete_rows_perm(hash_str):
    """deletes song entry from 'permanent' song list"""

    # find song with the hash
    result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                     range='datadump!G2:G').execute()

    row = -1
    for (i, entry) in reversed(list(enumerate(result['values']))):
        if len(entry) == 1 and entry[0] == hash_str:
            row = i
            break
    if row == -1:
        print('can\'t find song with provided hash')
        return

    delete_row_body = {"requests": [{"deleteDimension": {
        "range": {
            "sheetId": BACKUP_SHEET_ID,
            "dimension": "ROWS",
            "startIndex": row+1,
            "endIndex": row+2
        }
    }}, ], }
    result = SPREADSHEET.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body=delete_row_body).execute()

    # error logging
    open('log/reply.txt', 'a').write(str(result)+'\n')
    print('deleted entry ' + hash_str +
          ' (row ' + str(row+2) + ') from datadump')


def shadow(comment):
    """responds when nikos_bot acts"""

    if comment[-29:] == ' has been added to the queue.':
        find_and_add_song(comment)

    elif comment[-33:] == ', Successfully removed your song!':
        remove_song(comment)

    elif comment[:14] == 'Current song: ':
        update_song_list(comment)


def find_and_add_song(comment):
    """adds a song to songlist when nikos_bot added a song
    eg: 'Iceman1415 --> The song Smash Mouth - All Star has been added to the queue.'"""

    # parse nikos_bot's comment
    pos = comment.find(' --> The song ')
    requested_by = comment[:pos]
    song = comment[pos+14:-29].split(' - ')

    # generate a new spotify token for every query
    sp_token = sputil.prompt_for_user_token(SPOTIFY_USERNAME, SPOTIFY_SCOPE,
                                            client_id=SPOTIPY_CLIENT_ID,
                                            client_secret=SPOTIPY_CLIENT_SECRET,
                                            redirect_uri=SPOTIPY_REDIRECT_URI)
    spotify = spotipy.Spotify(auth=sp_token)
    sp_search_results = spotify.search(q=' '.join(song), limit=1)

    # parse search result
    sp_song = sp_search_results['tracks']['items'][0]
    song_name = sp_song['name']
    artist = sp_song['artists'][0]['name']
    sp_url = sp_song['external_urls']['spotify']
    song_duration = get_duration(sp_song['duration_ms'])

    # add song to song list
    add_song(song_name, artist,
             requested_by, song_duration, sp_url)


def remove_song(comment):
    """removes the song from song list when nikos_bot removed a song
    eg: 'Iceman1415, Successfully removed your song!'"""

    remover = comment[:-33]
    result = SPREADSHEET.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                     range='SongList!C2:G').execute()

    # find the location of song to remove
    hash_str = ''
    for i, entry in enumerate(result['values']):
        if entry[0].strip() == remover:
            row = i
            hash_str = entry[4].strip()
    row += 1

    if not hash_str:
        print("Error: no entry listed by " + remover)
    else:
        delete_rows_raw(row, row+1)
        delete_rows_perm(hash_str)


def update_song_list(comment):
    """updates song list to current position
    eg: 'Current song: Avenged Sevenfold - Hail to the King Requested by Luna_Eclipse0'"""

    pos = comment.rfind(' Requested by ')
    song_full = comment[14:pos].split(' - ')
    artist = song_full[0]
    song = ' '.join(song_full[1:])
    requested_by = comment[pos+14:]

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
