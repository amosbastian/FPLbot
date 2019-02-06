# FPLbot

FPLbot is a bot made for the subreddit [/r/FantasyPL](https://www.reddit.com/r/FantasyPL/).
It can also be used for other subreddits by changing the values in the
configuration file.

Its current features are:

* Posting the price changes of Fantasy Premier League players

## Installation

FPLbot uses MongoDB to store players in a database, and so it is required to
have MongoDB installed. Other than that, it uses [fpl](https://github.com/amosbastian/fpl)
to retrieve information from Fantasy Premier League's API, and thus requires
Python 3.6+.

    git clone git@github.com:amosbastian/FPLbot.git
    cd FPLbot
    pip install -r requirements.txt
    
To initialise the database you should do the following:

    python FPLbot/utils.py

Once this has been done, you can schedule a cron job to run the bot whenever you want!

## Configuration

|Option|Value|
|:-|:-|
|USERNAME|The bot's username|
|PASSWORD|The bot's password|
|CLIENT_ID|The bot's client ID|
|CLIENT_SECRET|The bot's client secret|
|USER_AGENT|A unique identifier that helps Reddit determine the source of network requests|
|SUBREDDIT|The subreddit the bot will post to|

For more information about how to set up a bot see [Reddit's guide](https://github.com/reddit-archive/reddit/wiki/OAuth2-Quick-Start-Example#first-steps).
