<h2 style="color: var(--burple);font-weight: 600;">Introduction</h2>
The core idea of Pixels is to have a collaborative canvas, where users paint pixel by pixel, by POSTing co-ordinates and a colour code to an API.

Our main goal for this project is to focus on it being a learning tool, for users who may not have previous experience with APIs.

With that said however, users of all experience levels are both welcome and encouraged to join in with the event!

<h2 style="color: var(--burple);font-weight: 600;">In-server</h2>
There are two channels within [Python Discord](https://discord.gg/python) related to this event:

<h3 style="color: var(--burple);font-weight: 600;">#pixels-discussion</h3>
This channel is for the main dicussion channel for all things Pixels! Find a team, discuss the current state of the canvas, ask for help setting up a script!

<h3 style="color: var(--burple);font-weight: 600;">#pixels-hook</h3>
This channel will relay the current state of the canvas every minute. This is where your work is shown off to other users, whether they're participating or not!


<h2 style="color: var(--burple);font-weight: 600;">A couple of prerequisites:</h2>

- The current API base location is at `https://pixels.pythondiscord.com`
- You will need the `requests` and `python-dotenv` modules to follow this guide.
    - Windows: `pip install requests python-dotenv`
    - Linux/Mac: `pip3 install requests python-dotenv`

A large asset to you while making API requests will be the [requests library documentation](https://docs.python-requests.org/en/master/).

<h2 style="color: var(--burple);font-weight: 600;">Authenticating with the API</h2>

API authentication is done using a bearer token in the `Authorization` header of requests made to the API. To obtain a bearer token for yourself, head to https://pixels.pythondiscord.com/authorize and follow the Discord OAuth flow.

Next, you'll want to keep that token safe in your preferred way of storing secrets. If you haven't dealt with storing secrets before you can utilise the widely used `.env` format.

Here's a brief example of how you can load your token from a `.env` file:

In a file named `.env`:
```
TOKEN='your_token_here'
```

In your main Python file:
```py
from dotenv import load_dotenv
from os import getenv

load_dotenv(".env")

token = getenv("TOKEN")
```

Note: you will need the `python-dotenv` (`pip install python-dotenv`) module installed so that you can use `load_dotenv`.

<h2 style="color: var(--burple);font-weight: 600;">Making a request</h2>

For this example we'll use the `/set_pixel` endpoint to set a specific pixel on the canvas. Firstly we want to import our HTTP library, for now we'll use the `requests` (`pip install requests`) library.

Let's start off with the `.env` token loading code we already have as a baseline:

```py
from dotenv import load_dotenv
from os import getenv

load_dotenv(".env")

token = getenv("TOKEN")
```

What we need to do now is import the requests library so that we can make requests, so we'll add that to the other imports at the top:

```py
from dotenv import load_dotenv
from os import getenv
import requests
```

From now on assume all code is below the `token = getenv("TOKEN")` line. We next need to create the authorization header for making API requests. We'll simply create a dict like the following:

```py
headers = {"Authorization": f"Bearer {token}"}
```

Next, we will create the actual data we're going to send to the API, in this case we will set the pixel at `(123, 12)` to the hex value `0x87CEEB`:

```py
data = {
    "x": 123,
    "y": 12,
    "rgb": "87CEEB",
}
```

Finally, we can make the API request itself, for which we'll need to use the `post` method of requests:

```py
result = requests.post("https://pixels.pythondiscord.com/set_pixel", json=data, headers=headers)
```

This code will create an HTTP POST request to `https://pixels.pythondiscord.com/set_pixel` with the authorization header `Bearer {the_token}` to set the pixel at `(123, 12)` to the hex value `0x87CEEB`, and store the result in the `result` variable.

To check that the request went through correctly we'll print out the confirmation message that the API provides us with:

```py
print(result.json()["message"])
```

Which will print, in this case, `added pixel at x=123,y=12 of color 87CEEB`.
