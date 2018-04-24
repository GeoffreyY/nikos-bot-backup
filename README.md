# nikos-bot-backup
quick and messy secondary twitch bot for twitch.tv/nikosstudios

I mainly made this to create a song list, as nikos' internet is too bad to sync his database / song queue online.
The bot now also provides a few minor functionalities.

The bot join the Twitch IRC channel, and 'shadows' the nikos_bot,
i.e. adding and removing songs only when nikos_bot comments that it has done so in chat.

We reverse search the song using spotipy, using information in nikos_bot's comment.
Then we append the entry onto a google spreadsheet.
