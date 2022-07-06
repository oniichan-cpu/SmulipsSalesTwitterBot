import requests
import time
import json
import tweepy
import yfinance as yf
from collections import deque
from bs4 import BeautifulSoup
import os

#Getting config datas
conf = open("./config/config.json")
config = json.load(conf)

#Currenciess
supported_fiat = ["EUR", "USD", "CAD", "JPY", "GPB", "AUD", "CNY", "INR"]

safety_delay = 0.05
delay = (1/config['TPS']) + safety_delay
refresh_delay = 1/config['refresh_delay']

#Queue to prevent double tweets
tweeted_queue = deque(maxlen=config['activities_per_call'])

client = tweepy.Client(bearer_token=os.environ["BEARER_TOKEN"],
                       consumer_key=os.environ["CONSUMER_KEY"],
                       consumer_secret=os.environ["CONSUMER_SECRET"],
                       access_token=os.environ["ACCESS_TOKEN"],
                       access_token_secret=os.environ["ACCESS_TOKEN_SECRET"])

auth = tweepy.OAuth1UserHandler(os.environ["CONSUMER_KEY"],
                                os.environ["CONSUMER_SECRET"],
                                os.environ["ACCESS_TOKEN"],
                                os.environ["ACCESS_TOKEN_SECRET"])

api = tweepy.API(auth)


# Gets the latest price of chosen crypto in chosen currency
def get_current_price(symbol):
    ticker = yf.Ticker(symbol)
    todays_data = ticker.history(period='1d')
    return todays_data['Close'][0]

# Fixing price got from trove
def fixed_price(pricePerItem):
    return str(int(pricePerItem)/1000000000000000000)

# Fetches metadata
def get_meta_from_mint():
    url = "https://api.thegraph.com/subgraphs/name/vinnytreasure/treasuremarketplace-fast-prod"
    payload = json.dumps({
        "query": "query getActivity($first: Int!, $skip: Int, $includeListings: Boolean!, $includeSales: Boolean!, $includeBids: Boolean!, $listingFilter: Listing_filter, $listingOrderBy: Listing_orderBy, $bidFilter: Bid_filter, $bidOrderBy: Bid_orderBy, $saleFilter: Sale_filter, $saleOrderBy: Sale_orderBy, $orderDirection: OrderDirection) {\n  listings(\n    first: $first\n    where: $listingFilter\n    orderBy: $listingOrderBy\n    orderDirection: $orderDirection\n    skip: $skip\n  ) @include(if: $includeListings) {\n    ...ListingFields\n  }\n  bids(\n    first: $first\n    where: $bidFilter\n    orderBy: $bidOrderBy\n    orderDirection: $orderDirection\n    skip: $skip\n  ) @include(if: $includeBids) {\n    ...BidFields\n  }\n  sales(\n    first: $first\n    where: $saleFilter\n    orderBy: $saleOrderBy\n    orderDirection: $orderDirection\n    skip: $skip\n  ) @include(if: $includeSales) {\n    ...SaleFields\n  }\n}\n\nfragment ListingFields on Listing {\n  timestamp\n  id\n  pricePerItem\n  quantity\n  seller {\n    id\n  }\n  token {\n    id\n    tokenId\n  }\n  collection {\n    id\n  }\n  currency {\n    id\n  }\n  status\n  expiresAt\n}\n\nfragment BidFields on Bid {\n  timestamp\n  id\n  pricePerItem\n  quantity\n  token {\n    id\n    tokenId\n  }\n  collection {\n    id\n  }\n  currency {\n    id\n  }\n  buyer {\n    id\n  }\n  status\n  expiresAt\n  bidType\n}\n\nfragment SaleFields on Sale {\n  timestamp\n  id\n  pricePerItem\n  quantity\n  type\n  seller {\n    id\n  }\n  buyer {\n    id\n  }\n  token {\n    id\n    tokenId\n  }\n  collection {\n    id\n  }\n  currency {\n    id\n  }\n}",
        "variables": {
            "skip": 0,
            "first": 200,
            "saleOrderBy": "timestamp",
            "saleFilter": {
                "collection": config['collection'],
                "timestamp_gte": 1656753149
            },
            "orderDirection": "desc",
            "includeListings": False,
            "includeSales": True,
            "includeBids": False
        },
        "operationName": "getActivity"
    })
    headers = {
        'authority': 'api.thegraph.com',
        'accept': '*/*',
        'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'content-type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload).json()
    temp = response['data']['sales'][0]
    return temp

# Converts tweet text to config text
def convert_tweet(meta):
    text = config['tweet_text']
    text = text.replace("[-n]", config['symbol'].capitalize())
    text = text.replace("[-t]",meta['token']['tokenId'])
    text = text.replace("[-f]",str(round((get_current_price("ETH-" + config['fiat_currency'])*float(fixed_price(meta['pricePerItem']))), 4)) + " " + config['fiat_currency'])
    text = text.replace("[-p]", fixed_price(meta['pricePerItem']) + " ETH")
    text = text.replace("[-l]","https://trove.treasure.lol/collection/"+config['symbol'].lower()+'/'+str(meta['token']['tokenId']))
    text = text.replace("[-h]", '#'+config['symbol'])
    return text

# Gets the link of image of the sold nft
def get_image(tokenId):
    html_page = requests.get("https://trove.treasure.lol/collection/"+config['symbol'].lower()+'/'+str(tokenId)).content

    soup = BeautifulSoup(html_page, "html.parser")
    images = []
    for img in soup.findAll('img'):
        images.append(img.get('src'))
    return images[0]

# Sends a tweet based on sale data and NFT metadata
def send_tweet(api, client ,meta):
    image = requests.get(meta['image'] if config['use_img_on_chain'] else get_image(meta['token']['tokenId'])).content
    with open('./tmp.png', 'wb') as handler:
        handler.write(image)
    #compress here

    mediaID = api.media_upload("tmp.png")
    try:
        client.create_tweet(text=convert_tweet(meta), media_ids=[mediaID.media_id])
        tweeted_queue.append(meta['id'])
    except:
        return

# Checking valid currency
if config['fiat_currency'] not in supported_fiat:
    print("INVALID FIAT_CURRENCY: CHECK CONFIG")

# Getting initial state of sales
previous_sales = []

print(f"WAITING FOR {config['symbol'].upper()} SALES")

c = 0
# Bot loop
while True:
    try:
        meta = get_meta_from_mint()
    except:
        continue
    new_sale = str(meta['id'])
    if new_sale not in previous_sales and new_sale not in tweeted_queue:
        try:
            time.sleep(delay)
            send_tweet(api, client, meta)
            previous_sales.append(meta['id'])
            print(f"Tweeting: {convert_tweet(meta)}")
        except:
            print(f"ERROR: ")
    time.sleep(refresh_delay)