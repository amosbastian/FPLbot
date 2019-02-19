# FPLbot

FPLbot is a bot made for the subreddit [/r/FantasyPL](https://www.reddit.com/r/FantasyPL/).
It can also be used for other subreddits by changing the values in the
configuration file.

Its current features are:

* Posting the price changes of Fantasy Premier League players
* Comparing the performance of a player vs. a team
* Comparing the performance of a palyer vs. another player

## Installation

FPLbot uses MongoDB to store players in a database, and so it is required to
have MongoDB installed. Other than that, it uses [fpl](https://github.com/amosbastian/fpl)
to retrieve information from Fantasy Premier League's API, and thus requires
Python 3.6+.

    git clone git@github.com:amosbastian/FPLbot.git
    cd FPLbot
    pip install -r requirements.txt
    
To initialise the database with text indexes you should do the following:

    python FPLbot/init.py

Once this has been done, you should create your own `config.json` with the correct values (see [configuration](#configuration)).
With this filled in, you can run the bot using

    python FPLbot/bot.py
    
As for the price changes, you should schedule a cron job, like this for example:

    25 1 * * * /home/amos/FPLbot/venv/bin/python /home/amos/FPLbot/FPLbot/price_changes.py
    
## Usage

The bot can be called on [/r/FantasyPL](https://www.reddit.com/r/FantasyPL/) using the following two commands:

1. `!fplbot <player_name> vs. <team_name> <optional: number of fixtures>`
2. `!fplbot <player_name> vs. <player_name> <optional: number of fixtures>`

The bot uses text indexes to search for the player(s) and using a manually created mapping (so you don't have to use e.g. "man utd" exactly, but other variations are fine as well, like "man u" or "manchester united"). The number of fixtures is completely optional, and if not specified, it simply uses *all* fixtures that are considered relevant. Here are two examples:

1.

    !fplbot heung-min son vs. mane 5

### Son (£8.9) vs. Mané (£9.6) (last 5 fixtures)

|xA|A|xG|G|MP|Fixture|Fixture|MP|G|xG|A|xA|
|-:|-:|-:|-:|-:|:-|-:|-:|-:|-:|-:|-:|
|0.13|0|0.42|1|**90**|Spurs 3-1 Leicester|Liverpool 3-0 Bournemouth|**89**|1|0.58|0|0.12|
|0.70|0|0.19|1|**90**|Spurs 1-0 Newcastle United|West Ham 1-1 Liverpool|**90**|1|0.64|0|0.00|
|0.00|0|0.20|1|**90**|Spurs 2-1 Watford|Liverpool 1-1 Leicester|**90**|1|0.18|0|0.10|
|0.38|0|0.05|0|**90**|Spurs 0-1 Man Utd|Liverpool 4-3 Crystal Palace|**90**|1|0.47|0|0.01|
|0.08|1|0.50|1|**77**|Cardiff 0-3 Spurs|Brighton 0-1 Liverpool|**90**|0|0.10|0|0.10|
|**1.29**|**1**|**1.36**|**4**|**437**|||**449**|**4**|**1.97**|**0**|**0.34**|

---

2.

    !fplbot rashford vs. liverpool
    
### Rashford vs. Liverpool (last 4 fixtures)

|Fixture|Date|MP|G|xG|A|xA|NPG|NPxG|KP|
|:-|:-|-:|-:|-:|-:|-:|-:|-:|-:|
|**Liverpool** 3-1 Man Utd|2018-12-16|**90**|0|0.02|0|0.00|0|0.02|0|
|**Man Utd** 2-1 Liverpool|2018-03-10|**72**|2|0.17|0|0.00|2|0.17|0|
|Liverpool 0-0 Man Utd|2017-10-14|24|0|0.00|0|0.00|0|0.00|0|
|Liverpool 0-0 Man Utd|2016-10-17|**78**|0|0.00|0|0.00|0|0.00|0|
|||**264**|**2**|**0.19**|**0**|**0.00**|**2.0**|**0.19**|**0**|

## Configuration

|Option|Value|
|:-|:-|
|USERNAME|The bot's username|
|PASSWORD|The bot's password|
|CLIENT_ID|The bot's client ID|
|CLIENT_SECRET|The bot's client secret|
|USER_AGENT|A unique identifier that helps Reddit determine the source of network requests|
|SUBREDDIT|The subreddit the bot will post to|
|BOT_PREFIX|The prefix used to call the bot, e.g.: "!fplbot"|

For more information about how to set up a bot see [Reddit's guide](https://github.com/reddit-archive/reddit/wiki/OAuth2-Quick-Start-Example#first-steps).
