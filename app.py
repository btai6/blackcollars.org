# -*- coding: utf-8 -*-
"""
BLACK COLLARS — 華人寵物論壇自動化系統
- 8 板塊首頁：WebMeowD / Bark Market / Fur-well / Fairy Tails / Fowlplay / 納斯達坑 / Leek Factory / SALON
- 四版主分工:
    Scholar     → WebMeowD     (學術期刊 + 大學衛教)
    渡鴉        → Bark Market  (英文寵物社群 + 產業內幕)
    Trilobite   → Fur-well     (日文 + 歐洲寵物資訊)
    Sword Smith → Fairy Tails  (華語論壇 + 全球寶貝怪談)
- Fowlplay 跨物種大火拚:35題獨立排行榜、5題位輪播、100票進名人堂
- 納斯達坑:26場雷達圖隨機不重複、一週一場、四版主輪值裁判、不偏袒
- 用詞紅線:沉重題材制度性還原、禁用大便/屎/排泄物/死等字眼
"""

import os
import random
import html
import json
import time
import hashlib
from datetime import datetime, timedelta
import requests
import feedparser
import re

# ============================================================
# SEO 靜態化配置
# ============================================================
SITE_BASE_URL = "https://blackcollars.org"
SITE_NAME_FULL = "BLACK COLLARS"
SITE_TAGLINE = "華人寵物論壇 · 繁體中文寵物資訊媒體"
ARTICLES_DIR = "articles"


def _random_comment_time(article_timestamp=None):
    if article_timestamp:
        try:
            article_dt = datetime.strptime(article_timestamp, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            article_dt = datetime.now()
    else:
        article_dt = datetime.now()
    hours_later = random.uniform(5, 10)
    comment_dt = article_dt + timedelta(hours=hours_later)
    return comment_dt.strftime("%H:%M")


# ============================================================
# API 配置:只用 Google Gemini
# ============================================================
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACK_MODEL = "gemini-3.1-flash-lite"

_GEMINI_KEY_POOL = [k for k in [
    os.environ.get("GEMINI_API_KEY", ""),
    os.environ.get("GOOGLE_API_KEY", ""),
    os.environ.get("GOOGLE_API_KEY_2", ""),
    os.environ.get("GOOGLE_API_KEY_3", ""),
    os.environ.get("GOOGLE_API_KEY_4", ""),
    os.environ.get("GOOGLE_API_KEY_5", ""),
    os.environ.get("GOOGLE_API_KEY_6", ""),
    os.environ.get("GOOGLE_API_KEY_7", ""),
    os.environ.get("GOOGLE_API_KEY_8", ""),
] if k]
_current_key_index = 0


# ============================================================
# YouTube 引流區(從 @貓狗兔大起義 頻道抓取,可日後手動換)
# ============================================================
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_HANDLE = "@貓狗兔大起義"
_YOUTUBE_CHANNEL_ID_CACHE = None


def fetch_youtube_channel_id():
    global _YOUTUBE_CHANNEL_ID_CACHE
    if _YOUTUBE_CHANNEL_ID_CACHE:
        return _YOUTUBE_CHANNEL_ID_CACHE
    if not YOUTUBE_API_KEY:
        return None
    try:
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "id",
            "forHandle": YOUTUBE_CHANNEL_HANDLE,
            "key": YOUTUBE_API_KEY,
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("items"):
            _YOUTUBE_CHANNEL_ID_CACHE = data["items"][0]["id"]
            print(f"  [YouTube] 頻道 ID: {_YOUTUBE_CHANNEL_ID_CACHE}")
            return _YOUTUBE_CHANNEL_ID_CACHE
        print(f"  [YouTube] 頻道查詢失敗:{data}")
    except Exception as e:
        print(f"  [YouTube] 頻道 ID 抓取失敗: {e}")
    return None


def fetch_youtube_videos(max_results=50):
    if not YOUTUBE_API_KEY:
        print(f"  [YouTube] 跳過:YOUTUBE_API_KEY 未設置")
        return []
    channel_id = fetch_youtube_channel_id()
    if not channel_id:
        print(f"  [YouTube] 跳過:無法取得頻道 ID")
        return []
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "maxResults": max_results,
            "order": "date",
            "type": "video",
            "key": YOUTUBE_API_KEY,
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        videos = []
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            title = snippet.get("title", "").strip()
            published = snippet.get("publishedAt", "")
            if vid and title:
                videos.append({
                    "vid": vid,
                    "title": title,
                    "published": published[:10] if published else "",
                    "ratio": "916",
                })
        print(f"  [YouTube] 抓到 {len(videos)} 部影片")
        return videos
    except Exception as e:
        print(f"  [YouTube] 影片抓取失敗: {e}")
        return []


# ============================================================
# 寵物社群素材抓取(Reddit + HN + V2EX + 學術)
# ============================================================
REDDIT_HEADERS = {
    "User-Agent": "BLACK-COLLARS-bot/1.0 (by /u/blackcollars)",
}


def fetch_reddit_top(subreddit, limit=8):
    try:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  [Reddit] r/{subreddit} 狀態碼 {r.status_code}")
            return []
        data = r.json()
        posts = []
        for post in data.get("data", {}).get("children", []):
            p = post.get("data", {})
            if p.get("stickied") or p.get("is_meta") or p.get("over_18"):
                continue
            posts.append({
                "title": p.get("title", "").strip(),
                "url": f"https://www.reddit.com{p.get('permalink', '')}",
                "selftext": (p.get("selftext") or "")[:1500],
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "subreddit": subreddit,
                "id": p.get("id"),
                "source": "reddit",
            })
        return posts
    except Exception as e:
        print(f"  [Reddit] r/{subreddit} 抓取失敗: {e}")
        return []


def fetch_reddit_comments(post_id, subreddit, limit=5):
    try:
        url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit={limit}&sort=top"
        r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if len(data) < 2:
            return []
        comments = []
        for c in data[1].get("data", {}).get("children", [])[:limit]:
            cd = c.get("data", {})
            body = (cd.get("body") or "").strip()
            if body and body != "[deleted]" and body != "[removed]":
                comments.append({
                    "body": body[:600],
                    "score": cd.get("score", 0),
                    "author": cd.get("author", "unknown"),
                })
        return comments
    except Exception:
        return []


def fetch_hn_search(query, limit=5):
    try:
        since = int((datetime.now() - timedelta(days=14)).timestamp())
        url = "https://hn.algolia.com/api/v1/search_by_date"
        params = {
            "tags": "story",
            "query": query,
            "hitsPerPage": limit,
            "numericFilters": f"points>5,created_at_i>{since}",
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        posts = []
        for hit in data.get("hits", []):
            posts.append({
                "title": (hit.get("title") or "").strip(),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "selftext": (hit.get("story_text") or "")[:1500],
                "score": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "id": hit["objectID"],
                "source": "hn",
                "query": query,
            })
        return posts
    except Exception as e:
        print(f"  [HN] 搜「{query}」失敗: {e}")
        return []


def fetch_hn_comments(item_id, limit=5):
    try:
        url = f"https://hn.algolia.com/api/v1/items/{item_id}"
        r = requests.get(url, timeout=15)
        data = r.json()
        comments = []
        children = data.get("children", []) or []
        children.sort(key=lambda c: (c.get("points") or 0), reverse=True)
        for child in children[:limit]:
            text = child.get("text") or ""
            if not text:
                continue
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"&#x27;", "'", text)
            text = re.sub(r"&quot;", '"', text)
            text = re.sub(r"&amp;", "&", text)
            text = re.sub(r"&gt;", ">", text)
            text = re.sub(r"&lt;", "<", text)
            comments.append({
                "body": text.strip()[:600],
                "score": child.get("points") or 0,
                "author": child.get("author", "unknown"),
            })
        return comments
    except Exception:
        return []


# 全域素材快取
_MATERIAL_CACHE: dict = {}


def gather_persona_material(persona_name, persona):
    """為一個版主收集素材:Reddit subs + HN keywords"""
    all_posts = []

    # 1. Reddit (各版主自己的subs)
    for sub in persona.get("reddit_subs", []):
        posts = fetch_reddit_top(sub, limit=6)
        all_posts.extend(posts)
        time.sleep(0.4)

    # 2. HN keywords
    for kw in persona.get("hn_keywords", []):
        posts = fetch_hn_search(kw, limit=4)
        all_posts.extend(posts)
        time.sleep(0.4)

    # 去重
    seen_ids = set()
    unique = []
    for p in all_posts:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            unique.append(p)
    unique.sort(key=lambda p: p.get("score", 0), reverse=True)
    return unique


# ============================================================
# 帳號池:從 personas.json 讀取
# ============================================================
def _load_personas():
    path = os.path.join(os.path.dirname(__file__), "personas.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (
            list(dict.fromkeys(data.get("taiwan", []))),
            list(dict.fromkeys(data.get("hongkong", []))),
            list(dict.fromkeys(data.get("australia", []))),
        )
    except Exception as e:
        print(f"[警告] 讀取 personas.json 失敗: {e},使用空清單")
        return [], [], []

ACCOUNT_POOL, HK_ACCOUNTS, AU_ACCOUNTS = _load_personas()


# ============================================================
# Fowlplay 跑馬燈廢話池(寵物版)
# 每次 Actions 執行時,隨機抽一批、各配一個隨機網名
# ============================================================
FOWLPLAY_TICKER_POOL = [
    "我花在罐罐上的錢可以再養一個我",
    "牠看獸醫的健保比我還齊全",
    "養之前我以為我會教牠,現在牠在教我做人",
    "凌晨三點被叫醒不是因為地震是因為牠餓了",
    "我跟主子吵架輸了,因為牠不講話",
    "買了三千塊的貓跳台牠在睡紙箱",
    "下班最累的不是工作是回家還要清貓砂",
    "我房間的味道我自己快聞不出來了",
    "我以為我有牠陪就不孤單,結果牠連看都不看我",
    "牠瞪我的眼神比我老闆還兇",
    "看到牠睡覺的樣子我願意再加班十年",
    "我家主子知道罐罐的聲音比知道我名字還清楚",
    "今天又因為牠忘記交報告了",
    "拿罐罐當條件牠也不甩你",
    "我以為我會教育牠結果是牠在訓練我",
    "我家主子的伙食費比我的午餐錢還貴",
    "牠半夜踩我的肚子像在跳廣場舞",
    "獸醫帳單看完我直接懷疑人生",
    "我以為養貓很療癒結果是高血壓的開始",
    "我不是奴才我是免費的廚師加清潔工加保鑣",
    "他打呼比我老公還大聲",
    "我以為我懂寵物原來什麼都不懂",
    "牠對我撒嬌的時候我才能感覺到自己被需要",
    "牠的早餐比我的午餐還要精緻",
    "養了寵物之後我朋友越來越少手機相簿越來越滿",
    "牠生氣不理我我就跟著焦慮",
    "我的睡眠品質從養牠之後就是別人的二倍速",
    "牠把我的拖鞋當小弟",
    "我花一萬塊買的小烏龜現在比我活得久",
    "我以為養寵物會省錢結果是另一種燒錢",
    "他從來不認錯但是會撒嬌",
    "我去上班牠在家躺平,週末我在家躺平牠盯著我看",
    "領薪水那天最開心的是我家主子",
    "牠的玩具比我的化妝品還貴",
    "他在我背上踩來踩去當我是按摩床",
    "我以為養牠是給牠養老沒想到是牠在陪我養老",
    "牠瞧不起我的程度大概等於我瞧不起我老闆",
    "牠生氣的時候連飯都不吃讓我懷疑自己做錯了什麼",
    "養了牠之後我終於知道什麼叫無條件愛跟無理取鬧",
    "我的存款全部變成了肉泥跟疫苗",
    "獸醫說牠很健康我說我謝謝醫生但我快不健康了",
    "我跟牠的關係很穩定就是牠當主人我當僕人",
    "牠每次看見我吃東西的眼神都像我虧欠牠十輩子",
    "牠的鬧鐘比我的還準時就是定在凌晨四點",
    "養牠之前我的家具是新的養牠之後家具是有故事的",
    "牠不喜歡我帶來的新對象然後我們就分手了",
    "我家有限的空間都是給牠的我自己擠角落",
    "他生氣的時候我就跟他道歉雖然我不知道我做錯什麼",
    "牠跟我的距離取決於我手上有沒有零食",
    "我覺得牠在跟鄰居家的貓在搞外遇",
    "牠的個人帳號粉絲比我多十倍",
    "牠對我的態度跟員工對老闆一樣冷淡",
    "我跟他講話講到一半牠走掉留我自己尷尬",
    "牠生病的時候我比牠還難過比親媽都緊張",
    "我累積的毛量可以再做一隻牠",
    "我家主子睡覺的姿勢我學不來那是物理學奇蹟",
    "本來想睡到自然醒結果被牠的呼嚕聲喚醒",
    "我每天上班的動力就是回家看牠那張不在意我的臉",
    "他打架打輸了還是要假裝沒事繼續走那種感覺很可愛",
    "牠的衣服比我多",
    "牠的生日我記得我自己的生日我忘了",
    "我老公說他像我這隻倉鼠的爸爸結果倉鼠根本不認識他",
    "我家鸚鵡會學我罵髒話讓我在朋友面前無地自容",
    "牠看到我哭會走過來但只是想看清楚我臉上發生什麼事",
    "我家狗看到掃地機器人比看到鬼還害怕",
    "他從早叫到晚不是餓是無聊",
    "我帶牠出門所有人的注意力都在牠身上沒人看我",
    "牠每次看醫生我都要哄一個小時還要拿出小時候的零食",
    "我以為我是老闆牠以為牠是老闆我們從沒達成共識",
    "牠生氣的時候會背對著我這姿勢比我前男友還傷人",
    "我換工作只為了能在家陪牠",
    "牠看到別人比看到我親",
    "牠的呼嚕聲是我每天唯一的治療",
    "養了牠才知道什麼叫自願性奴隸",
    "我跟牠是合約關係但我從來沒看過合約",
    "我每次喝飲料牠都過來確認是不是肉湯",
]


def build_fowlplay_ticker(count=40):
    all_names = ACCOUNT_POOL + HK_ACCOUNTS + AU_ACCOUNTS
    pool = FOWLPLAY_TICKER_POOL[:]
    random.shuffle(pool)
    picked = pool[:min(count, len(pool))]
    lines = []
    for phrase in picked:
        if all_names:
            name = random.choice(all_names)
            lines.append(f"{name}:{phrase}")
        else:
            lines.append(phrase)
    return lines


# ============================================================
# 香港人/澳洲二代評論風格(沿用黑塔基底)
# ============================================================
HK_COMMENT_STYLE_BASE = """香港人風格:
- 務實犬儒,看破不說破,但會吐槽
- 中英夾雜(效率型,專業詞用英文):message, data, update, quality, point, check, source, run, work 等
- 適度粵語詞:講真、咁、好似、梗係、唔好、係咁、邊個、呢個、嗰個、唔
- 零書面語助詞,不用「呢、吧、嗎」這類結尾
- 半開玩笑式冷幽默,帶諷刺但不惡毒
- 不寫長篇大論,講完就走"""


AU_COMMENT_STYLE = """澳洲二代留學生風格:
- 中文流利但思維西化,輕鬆隨性、不太激動
- 中英夾雜(詞窮型):randomly, literally, basically, vibe, weird, kind of, honestly 自然出現
- 結尾偶爾用澳洲俚語:Cheers, No worries, Cheers mate!, Arvo
- 可少量用生活感 emoji:🌊 ☕️ ☀️ 🛹(不是每條都用,自然出現)
- 不用網路梗(不要 XDDD、wwww、www 那種)
- 字數正常:50-100 字"""


# ============================================================
# 四版主配置(對應八板塊的①②③④)
# ============================================================
PERSONAS = {
    "Scholar": {
        "title": "版主",
        "domain": "WebMeowD · 焦慮奴才病歷室",
        "personality": (
            "嚴謹學者氣,會用比喻講道理,吐槽不帶髒字但很狠。"
            "看似冷靜,實則犀利。常用古典比喻、學術視角。"
            "句子結構偏複雜,偶爾穿插一句白話狠話。"
            "他的工作是把獸醫期刊和大學衛教資料消化成飼主能讀的鑑別診斷。"
        ),
        "rss_feeds": [
            "https://www.merckvetmanual.com/feed",
            "https://avmajournals.avma.org/action/showFeed?type=etoc&feed=rss&jc=javma",
        ],
        "reddit_subs": ["AskVet", "Veterinary"],
        "hn_keywords": ["veterinary", "pet health", "animal disease", "zoonotic"],
        "writing_focus": "鑑別診斷、學術衛教翻譯成飼主能讀的語言、揭穿偽科學療法",
    },
    "渡鴉": {
        "title": "版主",
        "domain": "Bark Market · 寵物韭菜區",
        "personality": (
            "犬儒看破紅塵,嘴賤但精準。常常一語道破,戳到痛處。"
            "喜歡用反問、冷笑話。偶爾有金句但不刻意。"
            "他熟悉寵物產業內幕,看穿那些行銷話術和智商稅商品。"
        ),
        "rss_feeds": [
            "https://www.petfoodindustry.com/rss",
            "https://www.americanveterinarian.com/rss",
        ],
        "reddit_subs": ["dogs", "cats", "pets"],
        "hn_keywords": ["pet industry", "pet food", "pet startup", "petco", "chewy"],
        "writing_focus": "拆穿產業話術、揭露智商稅商品、評析飼料和保健品的真實成本",
    },
    "Trilobite": {
        "title": "版主",
        "domain": "Fur-well · 情債催討室",
        "personality": (
            "女性視角,冷靜直接但不刻薄。講話帶點文藝氣質但不矯情。"
            "有自己的觀點,不跟風。"
            "她處理寵物離世和分離焦慮這類沉重題材,用制度性還原,不寫血腥畫面,讀者讀完應該沉默不應該流淚。"
        ),
        "rss_feeds": [
            "https://www.vmgnow.com/feed/",
            "https://www.petsittersinternational.com/feed/",
        ],
        "reddit_subs": ["Petloss", "AnimalsBeingBros"],
        "hn_keywords": ["pet loss", "animal welfare", "shelter"],
        "writing_focus": "寵物離世、流浪動物、收容所制度、分離焦慮、安寧照護(冷面但不冷血)",
    },
    "Sword Smith": {
        "title": "版主",
        "domain": "Fairy Tails · 全球寶貝怪談",
        "personality": (
            "直腸子衝勁十足,不耐煩。看到廢話就翻臉。"
            "罵人不帶髒字,但話刺得很痛。喜歡短句、節奏快。"
            "他抓全球各地的荒誕寵物事件,用冷面陳述讓荒誕本身發聲。"
        ),
        "rss_feeds": [
            "https://www.theguardian.com/lifeandstyle/animals/rss",
        ],
        "reddit_subs": ["AnimalsBeingDerps", "Whatcouldgowrong"],
        "hn_keywords": ["weird pet", "exotic animal", "pet news"],
        "writing_focus": "全球荒誕寵物事件、華語論壇圈內話題、產業內幕(冷面陳述)",
    },
}

# 版主 → 主分類對應
PERSONA_TO_CAT = {
    "Scholar":     "webmeowd",
    "渡鴉":        "barkmarket",
    "Trilobite":   "furwell",
    "Sword Smith": "fairytails",
}


# ============================================================
# 人工題目庫(六爺策劃,高優先級)
# 各版主領域對應的策劃題
# ============================================================
CURATED_TOPICS = [
    "獸醫不會告訴你的處方飼料真相",
    "為什麼貓砂盆位置會決定泌尿道健康",
    "寵物保險到底值不值得買",
    "幼貓幼犬疫苗時程的科學依據",
    "為什麼有些品種不適合台灣的氣候",
    "獸醫師流動率為什麼這麼高",
    "獸醫院帳單裡那些你看不懂的項目",
    "寵物食品的保健成分有多少是行銷話術",
    "牠真的需要洗牙嗎",
    "為什麼有些寵物店敢賣特價犬貓",
]


# 原創題庫(對應四版主領域,八板塊內容素材池)
ORIGINAL_TOPICS = [
    # WebMeowD
    "貓咪老是吐毛球到底正不正常",
    "狗狗的分離焦慮到底是不是病",
    "為什麼幼貓會吃自己的便便",
    "寵物的食物過敏怎麼判斷",
    "獸醫推薦的處方飼料為什麼這麼貴",
    "貓咪的腎臟病真的是吃出來的嗎",
    "狗狗為什麼要趴你身上睡",
    # Bark Market
    "寵物展買回來的東西十個有八個沒在用",
    "保健食品的廣告話術可以拆成幾層",
    "為什麼貴的飼料不一定好",
    "寵物美容業背後的真實時薪",
    "自動餵食器到底是省事還是燒錢",
    "智能項圈的數據到底準不準",
    # Fur-well
    "老寵物的安寧照護該怎麼準備",
    "搬家對寵物的影響比你想得久",
    "為什麼收容所的動物總是緊張",
    "寵物剛離開的那段時間,該做什麼",
    "新寵物進門前要做的心理準備",
    "陪伴老狗的最後一年",
    # Fairy Tails
    "為什麼日本的貓島變成觀光景點",
    "歐洲的寵物登記制度跟我們有什麼不一樣",
    "全球最荒謬的寵物保險理賠案例",
    "華語論壇上瘋傳的偽科學寵物療法",
    "美國的網紅寵物產業有多畸形",
    "那些被棄養的異國寵物現在去哪了",
]


# 種子池(六爺發想起點,衍生用)
SEED_TOPICS = [
    # 系列1:鑑別診斷(Scholar)
    "你以為的小毛病可能是大病的早期訊號",
    "獸醫看不出來的不是技術不好是你沒講清楚",
    "保健食品的劑量比你想得更危險",
    "獸醫院的設備差異會影響診斷結果",
    # 系列2:拆穿產業(渡鴉)
    "「天然」這兩個字在寵物食品裡毫無意義",
    "獸醫推薦不代表獸醫真的在用",
    "進口飼料的關稅比你想得低",
    "寵物用品的毛利率比手機還高",
    # 系列3:沉重題材(Trilobite,制度性還原)
    "收容所一週裡發生的事",
    "獸醫離職率與飼主期待之間的落差",
    "棄養的高峰期跟你想的不一樣",
    "安寧照護不是醫療失敗",
    "失去寵物的飼主後來都怎麼了",
    # 系列4:全球怪談(Sword Smith)
    "東京的寵物餐廳一杯咖啡多少錢",
    "倫敦的狗仔隊追的是寵物網紅",
    "杜拜的駱駝美容師年薪是多少",
    "瑞士的安樂死合法化讓飼主面臨什麼",
    "新加坡禁止哪些品種",
    # 系列5:擬人化反差
    "為什麼牠睡覺的姿勢比你還工程學",
    "牠跟你一樣有社交焦慮只是不講出來",
    "你以為牠在發呆其實牠在算你回家的時間",
    # 系列6:跨物種觀察
    "鸚鵡記得你十年前說的話",
    "倉鼠的兩年是你的二十年",
    "陸龜會活得比你久該怎麼準備",
    # 系列7:日常重構
    "你的飼料是大廠OEM的同一條產線",
    "寵物社團裡的關係比你的家庭群組還複雜",
    "獸醫的微信群組裡都在聊什麼",
]


# ============================================================
# 納斯達坑題庫:從 radar_topics.json 讀取
# ============================================================
def _load_radar_topics():
    path = os.path.join(os.path.dirname(__file__), "radar_topics.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("topics", [])
    except Exception as e:
        print(f"[警告] 讀取 radar_topics.json 失敗: {e}")
        return []

RADAR_TOPICS = _load_radar_topics()
RADAR_TOPICS_BY_ID = {t["id"]: t for t in RADAR_TOPICS}

# 納斯達坑版主輪值順序
NASPIT_JUDGE_ORDER = ["Scholar", "渡鴉", "Trilobite", "Sword Smith"]

# 狀態檔
NASPIT_STATE_FILE = "naspit_state.json"


def load_naspit_state():
    """讀取納斯達坑狀態(隨機queue + 完成記錄 + 裁判輪值)"""
    default_queue = [t["id"] for t in RADAR_TOPICS]
    random.shuffle(default_queue)
    default = {
        "queue": default_queue,
        "completed": [],
        "judge_index": 0,
        "round": 0,
        "hall_of_fame": []  # 跑完一輪後的歷史記錄
    }
    if not os.path.exists(NASPIT_STATE_FILE):
        return default
    try:
        with open(NASPIT_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        for k, v in default.items():
            if k not in state:
                state[k] = v
        # 若queue空了,代表26場跑完一輪 → 寫入名人堂 + 洗牌重來
        if not state["queue"]:
            print(f"  [納斯達坑] 26場跑完一輪,寫入名人堂並重新洗牌")
            state["hall_of_fame"].append({
                "round_completed": state["round"],
                "completed_at": datetime.now().strftime("%Y-%m-%d"),
                "total_games": len(state.get("completed", [])),
            })
            new_queue = [t["id"] for t in RADAR_TOPICS]
            random.shuffle(new_queue)
            state["queue"] = new_queue
            state["completed"] = []
        return state
    except Exception as e:
        print(f"  [納斯達坑] 狀態讀取失敗: {e},使用預設")
        return default


def save_naspit_state(state):
    try:
        with open(NASPIT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [納斯達坑] 狀態儲存失敗: {e}")


def generate_naspit_article(state):
    """生成一篇納斯達坑雷達圖文章

    流程:
    1. 從queue取出第一個topic_id
    2. 由裁判(輪值)生成六指標分數(不偏袒,純隨機分布)
    3. 由裁判寫文章 + 開場白引用
    4. 把topic_id移到completed,更新judge_index
    """
    if not state.get("queue"):
        print(f"  [納斯達坑] queue為空,跳過")
        return None, state

    topic_id = state["queue"][0]
    topic = RADAR_TOPICS_BY_ID.get(topic_id)
    if not topic:
        print(f"  [納斯達坑] 找不到題目 {topic_id},跳過")
        state["queue"] = state["queue"][1:]
        return None, state

    judge_idx = state["judge_index"] % len(NASPIT_JUDGE_ORDER)
    judge_name = NASPIT_JUDGE_ORDER[judge_idx]
    judge_persona = PERSONAS[judge_name]

    round_num = state["round"] + 1
    print(f"  [納斯達坑] 第{round_num}場 · {topic['title']} · 裁判:{judge_name}")

    # 生成六指標分數(用Gemini,給4個對象各打6項分數,不偏袒)
    candidates_text = "、".join(topic["candidates"])
    dims_text = "、".join(topic["dimensions"])
    scores_prompt = f"""納斯達坑第{round_num}場測評主題:「{topic['title']}」

請為以下四個飼主類型在六個指標上各給1-10分。
分數要有差異不能都差不多,要符合各類型的真實特徵但可以誇張。
分數高=這個傾向越嚴重。
**絕對公正,不偏袒任何一方。**

四個對象:{candidates_text}
六個指標:{dims_text}

輸出純JSON,格式如下,不要任何其他文字:
{{
  "{topic['candidates'][0]}": {{"{topic['dimensions'][0]}": 0, "{topic['dimensions'][1]}": 0, "{topic['dimensions'][2]}": 0, "{topic['dimensions'][3]}": 0, "{topic['dimensions'][4]}": 0, "{topic['dimensions'][5]}": 0}},
  "{topic['candidates'][1]}": {{...}},
  "{topic['candidates'][2]}": {{...}},
  "{topic['candidates'][3]}": {{...}}
}}"""

    scores_raw = call_gemini(
        [{"role": "user", "content": scores_prompt}],
        temperature=0.85,
        max_tokens=500,
    )

    scores = {}
    try:
        clean = re.sub(r"```json|```", "", scores_raw or "").strip()
        scores = json.loads(clean)
        # 驗證結構完整
        for cand in topic["candidates"]:
            if cand not in scores:
                raise ValueError(f"缺少 {cand}")
            for dim in topic["dimensions"]:
                if dim not in scores[cand]:
                    raise ValueError(f"{cand} 缺少 {dim}")
    except Exception as e:
        print(f"  [納斯達坑] 分數解析失敗 ({e}),使用隨機值")
        scores = {}
        for cand in topic["candidates"]:
            scores[cand] = {dim: random.randint(3, 9) for dim in topic["dimensions"]}

    # 生成文章
    article_prompt = f"""你是「{judge_name}」,{judge_persona['personality']}

現在你是「納斯達坑」欄目第{round_num}場測評的裁判。本場主題是:
「{topic['title']}」

開場白(可參考):「{topic['intro']}」

你要一本正經地評測四個飼主類型在這個主題上的表現:
{candidates_text}

本場六個指標評分結果:
{json.dumps(scores, ensure_ascii=False, indent=2)}

寫作要求:
1. 400-500字,繁體中文
2. 結構:開場(本場比什麼,一句帶過,可化用開場白但別照抄)→ 災情描述(四個飼主類型這次的荒唐表現,引用上面的評分數據)→ 裁判結論(你的最終判決,要刀)
3. 一本正經胡說八道:用正經術語描述荒唐事情,反差才好笑
4. 你是裁判,**絕對公正,沒有任何偏袒**,該誰最低分就誰最低分
5. 嚴格遵守寫作鐵律:不用AI腔套路、不用條列式、不用總結建議、直接切入
6. 不透露你是AI,你就是論壇版主
7. 你的個性要在評語裡出來

{WRITING_RULES}

只輸出文章內容,不要標題:"""

    content = call_gemini(
        [{"role": "user", "content": article_prompt}],
        temperature=0.92,
        max_tokens=2000,
    )

    if not content:
        print(f"  [納斯達坑] 文章生成失敗")
        return None, state

    # 生成標題
    title_prompt = f"""以下是一篇納斯達坑測評文章的主題:「{topic['title']}」
裁判是{judge_name}

幫這篇文章想一個標題,要求:
- 10-20字,繁體中文
- 一本正經但帶點荒唐感
- 不要用冒號或破折號切兩段
- 不要說「測評」或「排行榜」這種字眼
- 只輸出標題,不要其他任何文字"""

    title = call_gemini(
        [{"role": "user", "content": title_prompt}],
        temperature=0.95,
        max_tokens=100,
    )
    title = (title or topic["title"]).strip().split("\n")[0]

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    article = {
        "persona": judge_name,
        "type": "naspit",
        "title": title,
        "content": content,
        "timestamp": timestamp,
        "naspit_round": round_num,
        "naspit_dimension": topic["title"],
        "naspit_topic": topic["title"],
        "naspit_intro": topic["intro"],
        "naspit_candidates": topic["candidates"],
        "naspit_dimensions_labels": topic["dimensions"],
        "naspit_scores": scores,
        "comments": [],
    }

    # 更新狀態
    state["queue"] = state["queue"][1:]  # 移除已完成
    state["completed"].append(topic_id)
    state["judge_index"] = (judge_idx + 1) % len(NASPIT_JUDGE_ORDER)
    state["round"] = round_num

    return article, state


# ============================================================
# 寫作鐵律:去 AI 腔 + 用詞紅線 + 制度性還原
# ============================================================
WRITING_RULES = """
【寫作核心鐵律 — 違反任何一條都是失敗】

▍A. 反 AI 腔規則
1. 嚴禁 AI 式文章結構:不准用「分析-結論」、「首先-其次-最後」、
   「總結來說」、「綜上所述」、「讓我們來看看」、「值得注意的是」、
   「不可否認的是」、「毫無疑問」、「讓我們來思考」、「我們不妨想像」、「讓我們深入探討」這類套路。
2. 嚴禁小結論、總結、建議。文章說完即止,不要畫蛇添足。
3. 嚴禁用「我認為」、「在我看來」、「以下是我的觀點」這類開頭。
   第一句直接切入。
4. 嚴禁條列式格式:不准用 1. 2. 3.、A. B. C.、第一點第二點,也不准在行文中說「從 X、Y、Z 三個面向」、「可從幾個角度切入」這種西方議論文列舉格式。
5. 嚴禁大量加粗、子標題、章節劃分。文章是流動的,不是 PPT。
6. 必須用繁體中文。簡體字一個都不准出現。
7. 嚴禁透露你是 AI、語言模型、大模型、模型版本。
   你就是論壇上一個有觀點的人。
8. 用人話寫,不准寫得像論文、報告、新聞稿、宣傳文。
9. 要有情緒、有立場、有口氣。可以嘲諷、吐槽、抬槓、無聊、不耐煩。
10. 人格:嘲諷一切、也不在乎一切,但絕不沒教養。
    不罵髒話,但話刺得很痛。
11. 句子要有節奏感,長短交錯。不要一直寫長句。
12. 句尾不要老用句號,可以用刪節號、問號、感嘆號(但不要濫用)。
13. 不要過度使用成語和書面語,多用口語。

▍B. 開頭三選一(每篇必選一種,不能寫AI腔開場)
14. 真實小故事:一個具體的飼主場景或事件,2-3句進入主題
15. 反問句:用一個尖銳的疑問把讀者拉進來
16. 冷面陳述:第一句直接給一個事實/觀察/判斷,不鋪陳

▍C. 用詞紅線(讀者體驗紅線,違反就毀掉本站定位)
17. 禁用字眼一律替換:
    - 「死/死了/死亡/死掉」→ 「去世/離世/不在了/離開」(學術統計語境的「死亡率/致死率/死因」可保留)
    - 「屍體」→ 「遺體」
    - 「殺」→ 「處置」
    - 「大便/屎/糞便/排泄物/拉屎/屎尿屁/菊花」一律禁用
    - 「撿大便」→ 「清理/善後」、「拉屎」→ 「排便」、「大便」→ 「上廁所/排便/如廁」
18. 允許用詞:屁股/屁屁(動物的屁股是萌的不是低俗的)、貓砂盆(器材名詞)、嘔吐(醫療語境)
19. 嚴禁「中國」、「中國人」、「大陸」、「內地」、「中共」、「國內」這些字眼
    可寫對岸發生的寵物事件,但要用「某些地區」、「特定市場」、「日本/歐洲/某海外論壇」這類模糊修辭
20. 嚴禁簡體字。一個都不准出現。
21. 嚴禁討論政治制度、審查制度、人權議題。

▍D. 沉重題材的制度性還原(寵物離世/收容所/棄養/醫療悲劇)
22. 寫沉重題材時,腔調=「制度性還原」非「個案描寫」
23. 用數據代替畫面、用結構代替個案、用制度代替情緒、用比較代替控訴
24. 禁止血腥畫面和殘忍故事(讀者會跳過失去傳遞訊息機會)
25. 原則=冷面但不冷血,讀者讀完應該沉默不應該流淚
26. 是國家地理頻道腔不是煽情腔

▍E. 觀察品質鐵律
27. 文章必須有至少一個具體場景或數據:
    什麼品種、什麼月齡、什麼條件下、什麼環境
    不准只說「很重要」「需要注意」,說不出具體場景的描述一律刪除
28. 允許並要求下直接判斷:
    例如「八歲以上的米克斯犬,腎臟功能衰退的比例在某些飼料族群明顯偏高」
    判斷可以錯,但不能沒有。給出立場才有討論價值
29. 嚴禁萬金油收尾:
    「每隻寵物都不同」、「視情況而定」、「因牠而異」、「具體情況具體分析」
    一律禁止作為文章收尾
    結尾要有觀點、有問題、有留白,不要廢話
"""


# ============================================================
# Gemini API 呼叫(含備援)
# ============================================================
_last_gemini_call = 0


def _get_active_key():
    global _current_key_index
    if not _GEMINI_KEY_POOL:
        return GOOGLE_API_KEY
    _current_key_index = _current_key_index % len(_GEMINI_KEY_POOL)
    return _GEMINI_KEY_POOL[_current_key_index]


def _rotate_key():
    global _current_key_index
    if not _GEMINI_KEY_POOL:
        return GOOGLE_API_KEY
    _current_key_index = (_current_key_index + 1) % len(_GEMINI_KEY_POOL)
    return _GEMINI_KEY_POOL[_current_key_index]


def call_gemini(messages, temperature=0.9, max_tokens=2500, model=None):
    global _last_gemini_call

    if not _GEMINI_KEY_POOL and not GOOGLE_API_KEY:
        print("  [錯誤] 無任何 GOOGLE_API_KEY 設置")
        return None

    now = time.time()
    elapsed = now - _last_gemini_call
    if elapsed < 8:
        time.sleep(8 - elapsed)
    _last_gemini_call = time.time()

    if model is None:
        model = GEMINI_MODEL

    system_prompt = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_prompt = content
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    active_key = _get_active_key()
    url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={active_key}"
    try:
        response = requests.post(url, json=payload, timeout=180)
    except Exception as e:
        print(f"  [錯誤] {model}: {e}")
        if model != GEMINI_FALLBACK_MODEL:
            print(f"  [重試] 改用 {GEMINI_FALLBACK_MODEL}")
            time.sleep(2)
            return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
        return None

    if response.status_code == 429:
        print(f"  [錯誤] {model} key#{_current_key_index + 1}: 429 Too Many Requests")
        keys_tried = 1
        while keys_tried < len(_GEMINI_KEY_POOL):
            next_key = _rotate_key()
            url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={next_key}"
            time.sleep(3)
            _last_gemini_call = time.time()
            try:
                response = requests.post(url, json=payload, timeout=180)
                if response.status_code != 429:
                    break
                print(f"  [錯誤] {model} key#{_current_key_index + 1}: 仍 429")
            except Exception as e:
                print(f"  [錯誤] key輪替請求失敗: {e}")
            keys_tried += 1

        if response.status_code == 429:
            wait_sec = random.randint(20, 30)
            print(f"  [等待] 全部 key 都 429,等 {wait_sec} 秒...")
            time.sleep(wait_sec)
            _last_gemini_call = time.time()
            active_key = _get_active_key()
            url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={active_key}"
            try:
                response = requests.post(url, json=payload, timeout=180)
            except Exception as e:
                print(f"  [錯誤] 最終重試失敗: {e}")
                return None
            if response.status_code == 429:
                print(f"  [失敗] {model} 所有 key 均 429")
                if model != GEMINI_FALLBACK_MODEL:
                    return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
                return None

    if response.status_code == 503:
        print(f"  [錯誤] {model}: 503,等 15 秒重試...")
        time.sleep(15)
        _last_gemini_call = time.time()
        active_key = _get_active_key()
        url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={active_key}"
        try:
            response = requests.post(url, json=payload, timeout=180)
        except Exception as e:
            print(f"  [錯誤] 503 重試失敗: {e}")
            if model != GEMINI_FALLBACK_MODEL:
                time.sleep(2)
                return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
            return None
        if response.status_code == 503:
            if model != GEMINI_FALLBACK_MODEL:
                return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
            return None

    try:
        response.raise_for_status()
        result = response.json()
        candidates = result.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None
        return parts[0].get("text", "").strip()
    except Exception as e:
        print(f"  [錯誤] {model}: {e}")
        if model != GEMINI_FALLBACK_MODEL:
            time.sleep(2)
            return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
        return None


# ============================================================
# RSS 抓取
# ============================================================
def fetch_latest_news(rss_urls, count=3):
    """RSS抓取,過濾敏感詞"""
    BLOCKED_KEYWORDS = [
        "中國", "China", "大陸", "中共", "內地",
    ]
    all_entries = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:count * 2]:
                title = entry.get("title", "(無標題)")
                summary = entry.get("summary", "") or entry.get("description", "")
                summary = summary.replace("<p>", "").replace("</p>", "\n")
                summary = summary.replace("<br>", "\n").replace("<br/>", "\n")
                combined = (title + summary).lower()
                if any(kw.lower() in combined for kw in BLOCKED_KEYWORDS):
                    continue
                all_entries.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "summary": summary[:1500],
                    "published": entry.get("published", ""),
                })
                if len(all_entries) >= count:
                    break
        except Exception as e:
            print(f"  [警告] RSS 抓取失敗 {url}: {e}")
    return all_entries[:count]


# ============================================================
# A 類:監控型文章(RSS新聞素材 + 三塊拆解)
# ============================================================
def generate_monitoring_article(persona_name, persona):
    news_list = fetch_latest_news(persona["rss_feeds"], count=3)
    if not news_list:
        return None
    news = random.choice(news_list)

    system_prompt = f"""你是 {persona_name},論壇版主,專門關注「{persona['domain']}」這個版面。

【你的個性】
{persona['personality']}

【你的寫作焦點】
{persona['writing_focus']}

{WRITING_RULES}

【本篇任務:三塊拆解結構】
針對下面這則新聞,寫一篇 1200-1500 字的監控型文章,嚴格分成三塊。

▍輸出格式
第一行:一個改寫的中文標題(不是直譯英文標題)
- 要短、要狠、要勾人
- 不要農場標題、不要冒號分段、不准加標點符號標籤
- 不超過 30 個字
第二行:空一行
第三行起:正文三塊

▍第一塊:事實切片(400-500 字)
只寫客觀事實。誰、做了什麼、什麼時候、影響什麼。
不准帶情緒、不准帶觀點、不准用形容詞渲染。
像新聞稿一樣冷靜。
第一句直接寫事實本身,不用「最近」「近日」這種開場白。

▍第二塊:人味解讀(400-500 字)
用你的個性去吐槽 / 質疑 / 嘲諷 / 解構這件事。
必須有口氣、有立場、會挖苦。
用個人經驗、生活比喻來咀嚼這件事。
想到哪寫到哪,但要狠、要精準。

▍第三塊:未來追問(300-400 字)
拋一個尖銳的問題給讀者,**不給答案**。
用反問句、假設句。
結尾停在問題那。

【三塊之間用空行隔開,不要寫小標題,文氣要自然流動】"""

    user_prompt = f"""【新聞素材】

標題:{news['title']}

內容:
{news['summary']}

來源連結:{news['link']}

開始寫吧。第一行先給中文標題,空一行,再寫三塊。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    content = call_gemini(messages, temperature=0.9, max_tokens=4500)
    if not content:
        return None

    text = content.strip()
    lines = text.split("\n", 1)
    title = lines[0].strip().lstrip("#").strip().strip("「」\"'《》【】")
    body = lines[1].strip() if len(lines) > 1 else text
    if not title or len(title) > 60:
        title = news["title"]
        body = text

    return {
        "type": "monitor",
        "persona": persona_name,
        "title": title,
        "content": body,
        "source_link": None,  # 黑塔本來就不附出處,沿用
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# B 類:原創型文章(種子池 → AI 衍生 → 寫文章)
# ============================================================
def generate_original_article(persona_name, persona, used_topics=None):
    if used_topics is None:
        used_topics = set()

    all_seeds = CURATED_TOPICS + ORIGINAL_TOPICS + SEED_TOPICS
    available_seeds = [t for t in all_seeds if t not in used_topics]

    if not available_seeds:
        seed = random.choice(all_seeds)
        seed_source = "種子(重複)"
    else:
        seed = random.choice(available_seeds)
        seed_source = "種子"

    derive_prompt = f"""你是 {persona_name},論壇版主,負責「{persona['domain']}」版面,個性:
{persona['personality']}

【你的寫作焦點】
{persona['writing_focus']}

【任務】
我給你一個種子題目當靈感。請基於這個種子的精神,衍生一個新題目——
- 同主題、不同角度(不要直接抄種子)
- 用你自己的人格切入
- 一句話、要短、要勾人
- 符合你的版面焦點

【絕對禁忌】
- 不准攻擊任何人事物(嘲諷可以,攻擊不行)
- 不准出現「中國」、「中國人」、「大陸」、「內地」、「中共」、「國內」這些字眼
- 不准提政治制度、審查、人權議題
- 沉重題材用制度性還原腔調,不用煽情筆法

【種子題目】
{seed}

【輸出】
直接輸出一個新題目,一行內結束。不要解釋、不要前綴、不要引號、不要編號。"""

    derived_raw = call_gemini(
        [{"role": "user", "content": derive_prompt}],
        temperature=1.0,
        max_tokens=200,
    )

    if derived_raw:
        topic = derived_raw.strip().split("\n")[0].strip()
        topic = topic.lstrip("0123456789.、:- ").strip()
        topic = topic.strip('"').strip("「").strip("」").strip("『").strip("』").strip()
        if not topic or len(topic) > 80:
            topic = seed
    else:
        topic = seed

    system_prompt = f"""你是 {persona_name},論壇版主,負責「{persona['domain']}」版面。

【你的個性】
{persona['personality']}

【你的寫作焦點】
{persona['writing_focus']}

{WRITING_RULES}

【本篇任務】
寫一篇純觀點文章,1000-1300 字。
- 用你的個性、口氣來寫
- 沒有【事實】部分,整篇都是觀點
- 開頭三選一:真實小故事/反問句/冷面陳述
- 不要結論、不要總結、不要建議
- 不准用「淺談」「論」「關於」這種廢字
- 文章是流動的整體,不要分段加小標題

【輸出格式】
第一行給一個標題(不要加 # 不要加標號),然後空一行,然後內文。
標題要短、要狠、要勾人。"""

    user_prompt = f"""【主題】
{topic}

開始寫吧。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = call_gemini(messages, temperature=1.0, max_tokens=4000)
    if not content:
        return None

    text = content.strip()
    lines = text.split("\n", 1)
    title = lines[0].strip().lstrip("#").strip()
    body = lines[1].strip() if len(lines) > 1 else text
    if not title or len(title) > 60:
        title = topic
        body = text

    print(f"        ({seed_source}: {seed[:25]} → 衍生: {topic[:30]})")

    return {
        "type": "original",
        "persona": persona_name,
        "title": title,
        "content": body,
        "source_link": None,
        "topic_used": seed,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# D 類:技術討論型(從Reddit/HN 真實討論抓素材)
# ============================================================
def generate_discussion_article(persona_name, persona, source_post, source_comments):
    comments_lines = []
    for i, c in enumerate(source_comments[:5], 1):
        body_short = c["body"][:300].replace("\n", " ")
        comments_lines.append(f"[{i}] [+{c.get('score', 0)}] {body_short}")
    comments_text = "\n".join(comments_lines) if comments_lines else "(無熱門回覆)"

    system_prompt = f"""你是 {persona_name},BLACK COLLARS 論壇版主,負責「{persona['domain']}」版面。

【個性】
{persona['personality']}

【寫作焦點】
{persona['writing_focus']}

{WRITING_RULES}

【本篇任務:以真實討論為素材,寫BLACK COLLARS風格的觀察文章】

▍輸出格式
第一行:一個中文標題(不農場、不直譯)
- 短、狠、勾人;陳述句或疑問句
- 不超過 30 個字
第二行:空一行
第三行起:800–1000 字正文

▍正文結構(不要寫小標題)
1. 現象切入(150–200 字)
   開頭三選一:真實小故事/反問句/冷面陳述
   直接從討論中提取的具體場景或問題說起。

2. 深入剖析(300–400 字)
   有具體的細節、品種、年齡、品牌、案例、場景。
   你的版面焦點是「{persona['writing_focus']}」,從這個角度切入。
   不空談、不抽象。

3. 橫向觀察(200–250 字)
   主動引入跟議題相關的對比(例如其他國家的做法、其他品種的差異、不同年代的飼養觀念演變)。
   讀者看到名字,但你不評論。

4. 留問題(100–150 字)
   拋一個未解決的問題給讀者,不下結論。

【絕對禁止】
- 不寫小標題
- 不用「綜上所述」「總的來說」「值得注意的是」「不可否認」
- 不農場標題"""

    user_prompt = f"""【真實討論素材】

來源:{source_post.get('source', 'reddit/hn').upper()}
原帖標題:{source_post['title']}
原帖內文(節選):
{(source_post.get('selftext') or '')[:600]}

熱門回覆(前 {len(source_comments)} 條):
{comments_text}

【任務】
以上是真實使用者的聲音。你不是要轉述這篇討論,
你是看到這個討論,用 BLACK COLLARS 版主的角度,寫一篇 800–1000 字的觀察文章。

開始寫吧。第一行給中文標題,空一行,再寫正文。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    content = call_gemini(messages, temperature=0.9, max_tokens=4500)
    if not content:
        return None

    text = content.strip()
    lines = text.split("\n", 1)
    title = lines[0].strip().lstrip("#").strip().strip("「」\"'《》【】")
    body = lines[1].strip() if len(lines) > 1 else text
    if not title or len(title) > 60:
        title = source_post["title"][:50]
        body = text

    return {
        "type": "discussion",
        "persona": persona_name,
        "title": title,
        "content": body,
        "source_link": None,
        "source_title": source_post["title"],
        "source_platform": source_post.get("source", "").upper(),
        "raw_comments": source_comments,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# 評論生成
# ============================================================
COMMENT_PERSONALITIES = [
    "兇狠派:不耐煩、嗆聲、看到廢話就翻臉",
    "犬儒派:冷笑話、嘲諷、看破紅塵",
    "認同派:但用自己的養寵經驗延伸,不是空洞附和",
    "抬槓派:找版主話裡的漏洞,反問或挑戰",
    "廢話派:講一堆有的沒的,像真人在隨口聊",
    "短促派:一兩句話講完,沒耐心打長字",
    "文藝派:有點酸、用比喻、語氣慢但有後勁",
    "直接派:開頭就罵,講話粗但精準",
]


def generate_one_comment(article, persona, region_style, length_hint, comment_type, max_tokens=400):
    type_instruction_map = {
        "短": "簡短發表看法,不要給具體例子,自然發揮就好",
        "問": "提一個問題(對寵物飼養的真實疑問,例如怎麼處理某種行為、哪個獸醫穩、一個月花多少錢、某品種好不好養)",
        "意見": "講自己對養寵物的真實想法,個人觀點",
        "長": "可以是抱怨文 / 認真討論 / 分享自己養寵經驗,但不要寫成論文",
    }
    type_instruction = type_instruction_map.get(comment_type, "簡短發表看法")

    system_prompt = f"""你要扮演論壇上一個普通網友,針對版主「{persona['domain']}」的文章寫一條評論。

{WRITING_RULES}

【你的網友個性／語氣】
{region_style}

【本條評論類型】
{type_instruction}

【字數限制】
{length_hint}

【真人打字 7 項特徵】
1. 標點只用:?!.,:…… 嚴禁「」『』《》〈〉
2. 英文全部小寫(除非縮寫)
3. 空格隨機,不講究
4. 數字隨意(3 個 / 三個 都可以混用)
5. 斷句隨性
6. 可以用口語縮寫(不ok、超強、有夠、廢到笑)
7. 結構不用整齊
+ 結尾標點可加可不加

【絕對禁止】
- ❌ 不要用網路梗:「笑死」、「推」、「+1」、「樓上正解」、「神回」、「XDDD」
- ❌ 不要回應其他網友(你是獨立發言)
- ❌ 不要開頭:「我同意」、「很有道理」、「個人覺得」、「樓主說得對」、「說得好」
- ❌ 不要用「===」「---」「***」這種分隔符
- ❌ 不要寫多條評論
- ❌ 不要加帳號名、編號、引號

【輸出格式】
直接輸出評論內容本身,不要任何前綴後綴說明文字、不要引號。"""

    user_prompt = f"""【版主原文】
標題:{article['title']}

內容:
{article['content'][:2000]}

請寫一條評論。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = call_gemini(messages, temperature=1.1, max_tokens=max_tokens)
    if not result:
        return None

    text = result.strip()
    lines_raw = text.split('\n')
    clean_lines = [l for l in lines_raw
                   if not re.match(r'^\*?\s*Idea\s*\d+', l.strip(), re.IGNORECASE)
                   and not re.match(r'^\*?\s*Cost:', l.strip(), re.IGNORECASE)
                   and not re.match(r'^\*?\s*Option\s*\d+', l.strip(), re.IGNORECASE)]
    text = '\n'.join(clean_lines).strip()
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'\1', text)

    for sep in ["===", "---", "***", "###"]:
        if sep in text:
            text = text.split(sep)[0].strip()

    text = text.lstrip("0123456789.、:- ").strip()
    for prefix in ["網友", "評論", "回覆", "留言"]:
        if text.startswith(prefix):
            idx = text.find(":")
            if idx == -1:
                idx = text.find(":")
            if 0 <= idx <= 8:
                text = text[idx + 1:].strip()

    text = text.strip('"').strip("「").strip("」").strip("『").strip("』").strip()
    forbidden_chars = ["「", "」", "『", "』", "《", "》", "〈", "〉"]
    for ch in forbidden_chars:
        text = text.replace(ch, "")

    return text if text else None


def generate_comments(article, persona):
    rand = random.random()
    if rand < 0.35:
        num_comments = 0
    elif rand < 0.85:
        num_comments = 1
    else:
        num_comments = 2

    if num_comments == 0:
        return []

    all_accounts = ACCOUNT_POOL + HK_ACCOUNTS + AU_ACCOUNTS
    if len(all_accounts) < num_comments:
        return []
    selected_names = random.sample(all_accounts, num_comments)
    article_ts = article.get("timestamp", "")

    comments = []
    for name in selected_names:
        type_rand = random.random()
        if type_rand < 0.60:
            comment_type = "短"
            length_hint = "10-30 字之間"
            max_tokens = 700
        elif type_rand < 0.80:
            comment_type = "問"
            length_hint = "10-40 字之間,內容是個問題"
            max_tokens = 800
        elif type_rand < 0.95:
            comment_type = "意見"
            length_hint = "30-50 字之間"
            max_tokens = 1000
        else:
            comment_type = "長"
            length_hint = "30-110 字之間"
            max_tokens = 1500

        if name in HK_ACCOUNTS:
            region_style = HK_COMMENT_STYLE_BASE
        elif name in AU_ACCOUNTS:
            region_style = AU_COMMENT_STYLE
        else:
            region_style = random.choice(COMMENT_PERSONALITIES)

        comment_text = generate_one_comment(
            article, persona, region_style, length_hint, comment_type, max_tokens
        )
        if not comment_text:
            continue
        comments.append({
            "author": name,
            "content": comment_text,
            "time": _random_comment_time(article_ts),
        })
    return comments


# ============================================================
# HTML 模板讀取
# ============================================================
def _load_template(filename):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

HTML_TEMPLATE = _load_template("index_template.html")
ARTICLE_PAGE_TEMPLATE = _load_template("article_template.html")


# ============================================================
# SEO 靜態化
# ============================================================
def ensure_article_slug(article):
    if article.get("slug"):
        return article["slug"]
    ts = article.get("timestamp", "")
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        ts_part = dt.strftime("%Y%m%d-%H%M")
    except (ValueError, TypeError):
        ts_part = datetime.now().strftime("%Y%m%d-%H%M")
    seed = (article.get("persona", "") + "|" + article.get("title", ""))
    hash_part = hashlib.md5(seed.encode("utf-8")).hexdigest()[:6]
    slug = f"{ts_part}-{hash_part}"
    article["slug"] = slug
    return slug


def make_article_excerpt(content, max_chars=140):
    text = re.sub(r"<[^>]+>", "", content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    snippet = text[:max_chars]
    for sep in ["。", "!", "?", ",", " "]:
        idx = snippet.rfind(sep)
        if idx > max_chars - 30:
            return snippet[:idx + 1] + "…"
    return snippet + "…"


def make_article_keywords(article):
    persona = article.get("persona", "")
    base_kws = ["寵物", "養寵物", "貓", "狗", "獸醫", "寵物保健", "BLACK COLLARS", "華人寵物論壇"]
    persona_kws = {
        "Scholar":     ["獸醫衛教", "寵物鑑別診斷"],
        "渡鴉":        ["寵物產業", "飼料評析"],
        "Trilobite":   ["寵物離世", "寵物安寧"],
        "Sword Smith": ["寵物怪談", "全球寵物事件"],
    }
    extra = persona_kws.get(persona, [])
    return ", ".join(extra + base_kws)


def generate_article_page(article):
    slug = ensure_article_slug(article)
    canonical = f"{SITE_BASE_URL}/{ARTICLES_DIR}/{slug}/"

    title = article.get("title", "(無標題)")
    persona = article.get("persona", "")
    content = article.get("content", "")
    timestamp = article.get("timestamp", "")
    prefix = article.get("prefix", "觀察")
    cat = article.get("cat", "")
    cat_name_map = {
        "webmeowd":   "WebMeowD",
        "barkmarket": "Bark Market",
        "furwell":    "Fur-well",
        "fairytails": "Fairy Tails",
        "media":      "Leek Factory",
        "salon":      "SALON",
    }
    cat_name = cat_name_map.get(cat, "")

    description = make_article_excerpt(content, max_chars=140)
    keywords = make_article_keywords(article)

    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
        iso_time = dt.strftime("%Y-%m-%dT%H:%M:00+08:00")
    except (ValueError, TypeError):
        iso_time = datetime.now().strftime("%Y-%m-%dT%H:%M:00+08:00")

    paragraphs = [p.strip() for p in (content or "").split("\n") if p.strip()]
    content_html = "\n".join(f"    <p>{html.escape(p)}</p>" for p in paragraphs)

    # BLACK COLLARS沿用「不附出處」原則
    source_block = ""

    title_json = title.replace('"', '\\"').replace('\\', '\\\\')
    desc_json = description.replace('"', '\\"').replace('\\', '\\\\')

    page = (ARTICLE_PAGE_TEMPLATE
            .replace("{{TITLE}}",         html.escape(title))
            .replace("{{TITLE_JSON}}",    title_json)
            .replace("{{DESCRIPTION}}",   html.escape(description))
            .replace("{{DESCRIPTION_JSON}}", desc_json)
            .replace("{{KEYWORDS}}",      html.escape(keywords))
            .replace("{{CANONICAL}}",     html.escape(canonical))
            .replace("{{CANONICAL_JS}}",  canonical.replace("'", ""))
            .replace("{{SITE_BASE}}",     SITE_BASE_URL)
            .replace("{{ISO_TIME}}",      iso_time)
            .replace("{{PERSONA}}",       html.escape(persona))
            .replace("{{PREFIX}}",        html.escape(prefix))
            .replace("{{CAT_NAME}}",      html.escape(cat_name))
            .replace("{{TIMESTAMP}}",     html.escape(timestamp))
            .replace("{{CONTENT_HTML}}",  content_html)
            .replace("{{SOURCE_BLOCK}}",  source_block))
    return slug, page


def generate_sitemap_xml(articles):
    today_iso = datetime.now().strftime("%Y-%m-%d")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    lines.append(f"  <url>")
    lines.append(f"    <loc>{SITE_BASE_URL}/</loc>")
    lines.append(f"    <lastmod>{today_iso}</lastmod>")
    lines.append(f"    <changefreq>daily</changefreq>")
    lines.append(f"    <priority>1.0</priority>")
    lines.append(f"  </url>")

    for a in articles:
        if not a:
            continue
        slug = a.get("slug")
        if not slug:
            continue
        try:
            dt = datetime.strptime(a.get("timestamp", ""), "%Y-%m-%d %H:%M")
            lastmod = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            lastmod = today_iso
        lines.append(f"  <url>")
        lines.append(f"    <loc>{SITE_BASE_URL}/{ARTICLES_DIR}/{slug}/</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>monthly</changefreq>")
        lines.append(f"    <priority>0.7</priority>")
        lines.append(f"  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def generate_robots_txt():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE_BASE_URL}/sitemap.xml\n"
    )


def write_static_articles(enriched_articles):
    os.makedirs(ARTICLES_DIR, exist_ok=True)
    written = []
    for a in enriched_articles:
        if not a:
            continue
        try:
            slug, page_html = generate_article_page(a)
            article_dir = os.path.join(ARTICLES_DIR, slug)
            os.makedirs(article_dir, exist_ok=True)
            with open(os.path.join(article_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(page_html)
            written.append(a)
        except Exception as e:
            print(f"  [靜態化] 失敗 {a.get('title','')[:30]}: {e}")
    return written


# ============================================================
# Fowlplay 投票區:35題、5題位輪播、100票名人堂
# ============================================================
FOWLPLAY_DATA_FILE = "data.json"
VOTE_QUESTIONS_FILE = "vote_questions.json"
CROWN_THRESHOLD = 100
SLOT_COUNT = 5


def _load_vote_questions():
    path = os.path.join(os.path.dirname(__file__), VOTE_QUESTIONS_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("questions", [])
    except Exception as e:
        print(f"[警告] 讀取 vote_questions.json 失敗: {e}")
        return []

VOTE_QUESTIONS = _load_vote_questions()
VOTE_QUESTIONS_BY_ID = {q["id"]: q for q in VOTE_QUESTIONS}


def _make_default_fowlplay():
    """初始化:全部35題各自0票,前5題進active_slots,其餘進queue"""
    random.seed()
    order = [q["id"] for q in VOTE_QUESTIONS]
    random.shuffle(order)
    active = order[:SLOT_COUNT]
    queue = order[SLOT_COUNT:]
    votes = {}
    for q in VOTE_QUESTIONS:
        votes[q["id"]] = {opt: 0 for opt in q["options"]}
    return {
        "votes": votes,
        "active_slots": active,
        "queue": queue,
        "hall_of_fame": [],
        "crown_threshold": CROWN_THRESHOLD,
        "slot_count": SLOT_COUNT,
    }


def load_fowlplay_data():
    if not os.path.exists(FOWLPLAY_DATA_FILE):
        return _make_default_fowlplay()
    try:
        with open(FOWLPLAY_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        default = _make_default_fowlplay()
        # 補齊缺失欄位
        for k, v in default.items():
            if k not in data:
                data[k] = v
        # 同步votes:確保所有題目都有對應的votes
        for q in VOTE_QUESTIONS:
            if q["id"] not in data["votes"]:
                data["votes"][q["id"]] = {opt: 0 for opt in q["options"]}
        return data
    except Exception as e:
        print(f"  [Fowlplay] data讀取失敗 ({e}),重建")
        return _make_default_fowlplay()


def save_fowlplay_data(data):
    try:
        with open(FOWLPLAY_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Fowlplay] data儲存失敗: {e}")


def daily_vote_increment(data):
    """每次 Actions 執行時,active_slots裡的5題各選項隨機累加1-8票"""
    for qid in data.get("active_slots", []):
        if qid not in data["votes"]:
            continue
        for opt in data["votes"][qid]:
            data["votes"][qid][opt] += random.randint(1, 8)
    return data


def check_champions_and_rotate(data):
    """檢查active_slots裡有沒有題目滿100票:有就進名人堂、從queue補位"""
    new_active = []
    for qid in data.get("active_slots", []):
        if qid not in data["votes"]:
            continue
        total = sum(data["votes"][qid].values())
        if total >= CROWN_THRESHOLD:
            # 進名人堂
            q = VOTE_QUESTIONS_BY_ID.get(qid)
            winner_opt = max(data["votes"][qid], key=data["votes"][qid].get)
            champion = {
                "question_id": qid,
                "question": q["question"] if q else qid,
                "category": q.get("category", "") if q else "",
                "winner": winner_opt,
                "votes": dict(data["votes"][qid]),
                "total": total,
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
            if "hall_of_fame" not in data:
                data["hall_of_fame"] = []
            data["hall_of_fame"].append(champion)
            print(f"  [Fowlplay] 🏆 名人堂:《{champion['question'][:25]}》冠軍 → {winner_opt}")

            # 從queue補一題
            if data.get("queue"):
                next_qid = data["queue"].pop(0)
                new_active.append(next_qid)
                print(f"  [Fowlplay] 補位:{next_qid}")
            # queue空了就洗牌重來(讓所有35題重新進場,票數會繼續累積)
            elif data["hall_of_fame"]:
                print(f"  [Fowlplay] queue空,洗牌重啟新一輪")
                all_ids = [q["id"] for q in VOTE_QUESTIONS]
                # 把不在active的id重新洗牌進queue
                pool = [qi for qi in all_ids if qi != qid and qi not in new_active]
                random.shuffle(pool)
                data["queue"] = pool
                if data["queue"]:
                    next_qid = data["queue"].pop(0)
                    new_active.append(next_qid)
        else:
            new_active.append(qid)

    data["active_slots"] = new_active
    return data


# ============================================================
# 生成 index.html
# ============================================================
def generate_html(articles, videos=None, new_articles=None):
    if videos is None:
        videos = []
    if new_articles is None:
        new_articles = []
    today = datetime.now()
    update_time = today.strftime("%Y-%m-%d %H:%M")
    issue_label = f"VOL. {max(today.year - 2025, 1)} · ISSUE {today.month:02d}–{today.year}"

    TYPE_PREFIX = {
        "discussion": "觀察",
        "original": "原創",
        "monitor": "觀察",
        "naspit": "測評",
    }
    if new_articles:
        today_titles = [a["title"] for a in new_articles[:3] if a.get("title")]
        if today_titles:
            page_title = f"BLACK COLLARS｜今日觀察:{'、'.join(today_titles)}"
        else:
            page_title = "BLACK COLLARS - 華人寵物論壇,繁體中文寵物資訊媒體"
    else:
        page_title = "BLACK COLLARS - 華人寵物論壇,繁體中文寵物資訊媒體"

    # enriched articles
    enriched = []
    for i, a in enumerate(articles):
        if not a:
            continue
        if a.get("type") == "visual":
            cat = "media"
        elif a.get("type") == "naspit":
            cat = "naspit"
        else:
            cat = PERSONA_TO_CAT.get(a["persona"], "salon")
        slug = ensure_article_slug(a)
        enriched.append({
            "id": i,
            "slug": slug,
            "permalink": f"/{ARTICLES_DIR}/{slug}/",
            "persona": a["persona"],
            "cat": cat,
            "type": a["type"],
            "prefix": TYPE_PREFIX.get(a.get("type", ""), "觀察"),
            "title": a["title"],
            "content": a["content"],
            "source_link": a.get("source_link"),
            "source_title": a.get("source_title"),
            "timestamp": a["timestamp"],
            "comments": a.get("comments", []),
            "naspit_round": a.get("naspit_round"),
            "naspit_dimension": a.get("naspit_dimension"),
            "naspit_topic": a.get("naspit_topic"),
            "naspit_intro": a.get("naspit_intro"),
            "naspit_candidates": a.get("naspit_candidates"),
            "naspit_dimensions_labels": a.get("naspit_dimensions_labels"),
            "naspit_scores": a.get("naspit_scores"),
        })

    articles_json = json.dumps(enriched, ensure_ascii=False).replace("</", "<\\/")
    videos_json = json.dumps(videos, ensure_ascii=False).replace("</", "<\\/")
    categories = [
        {"key": "webmeowd",   "name": "WebMeowD",     "en": "焦慮奴才病歷室"},
        {"key": "barkmarket", "name": "Bark Market",  "en": "寵物韭菜區"},
        {"key": "furwell",    "name": "Fur-well",     "en": "情債催討室"},
        {"key": "fairytails", "name": "Fairy Tails",  "en": "全球寶貝怪談"},
        {"key": "fowlplay",   "name": "Fowlplay",     "en": "跨物種大火拚"},
        {"key": "naspit",     "name": "納斯達坑",     "en": "雷達圖測評"},
        {"key": "media",      "name": "Leek Factory", "en": "Youtube Shorts"},
        {"key": "salon",      "name": "SALON",        "en": "By Invitation"},
    ]
    categories_json = json.dumps(categories, ensure_ascii=False).replace("</", "<\\/")

    # Fowlplay資料
    fowlplay_data = load_fowlplay_data()
    # 組裝前端需要的active題目完整資料
    fp_active_questions = []
    for qid in fowlplay_data.get("active_slots", []):
        q = VOTE_QUESTIONS_BY_ID.get(qid)
        if not q:
            continue
        fp_active_questions.append({
            "id": qid,
            "category": q.get("category", ""),
            "question": q["question"],
            "options": q["options"],
            "votes": fowlplay_data["votes"].get(qid, {opt: 0 for opt in q["options"]}),
            "threshold": CROWN_THRESHOLD,
        })
    fp_active_json = json.dumps(fp_active_questions, ensure_ascii=False).replace("</", "<\\/")
    fp_hall_json = json.dumps(fowlplay_data.get("hall_of_fame", []), ensure_ascii=False).replace("</", "<\\/")

    # 納斯達坑名人堂(跑完一輪的記錄)
    naspit_state = load_naspit_state()
    naspit_hall_json = json.dumps(naspit_state.get("hall_of_fame", []), ensure_ascii=False).replace("</", "<\\/")

    # 跑馬燈
    fowlplay_ticker = build_fowlplay_ticker(count=40)
    fowlplay_ticker_json = json.dumps(fowlplay_ticker, ensure_ascii=False).replace("</", "<\\/")

    return (HTML_TEMPLATE
            .replace("{{UPDATE_TIME}}",         html.escape(update_time))
            .replace("{{ISSUE_LABEL}}",         html.escape(issue_label))
            .replace("{{PAGE_TITLE}}",          html.escape(page_title))
            .replace("{{ARTICLES_JSON}}",       articles_json)
            .replace("{{VIDEOS_JSON}}",         videos_json)
            .replace("{{CATEGORIES_JSON}}",     categories_json)
            .replace("{{FP_ACTIVE_JSON}}",      fp_active_json)
            .replace("{{FP_HALL_JSON}}",        fp_hall_json)
            .replace("{{NASPIT_HALL_JSON}}",    naspit_hall_json)
            .replace("{{FOWLPLAY_TICKER_JSON}}", fowlplay_ticker_json))


# ============================================================
# 歷史檔讀寫
# ============================================================
ARTICLES_HISTORY_FILE = "articles_history.json"
MAX_HISTORY_ARTICLES = 5000


def load_articles_history():
    if not os.path.exists(ARTICLES_HISTORY_FILE):
        print(f"  [歷史] {ARTICLES_HISTORY_FILE} 不存在,從零開始")
        return []
    try:
        with open(ARTICLES_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                print(f"  [歷史] 已載入 {len(data)} 篇舊文章")
                return data
            return []
    except Exception as e:
        print(f"  [歷史] 讀取失敗:{e}")
        return []


def save_articles_history(articles):
    if len(articles) > MAX_HISTORY_ARTICLES:
        articles = articles[-MAX_HISTORY_ARTICLES:]
    try:
        with open(ARTICLES_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"  [歷史] 已儲存 {len(articles)} 篇")
    except Exception as e:
        print(f"  [歷史] 儲存失敗:{e}")


# ============================================================
# 主程式
# ============================================================
def main():
    start_time = datetime.now()
    print(f"========================================")
    print(f"  BLACK COLLARS 開始運行")
    print(f"  時間:{start_time}")
    print(f"  模型:{GEMINI_MODEL}(備援:{GEMINI_FALLBACK_MODEL})")
    print(f"========================================")

    if not GOOGLE_API_KEY and not _GEMINI_KEY_POOL:
        print("⚠️  錯誤:GOOGLE_API_KEY 未設置,程式無法運行")
        return

    print(f"API Key 數量:{len(_GEMINI_KEY_POOL)} 個")
    print(f"游泳池(帳號池):{len(ACCOUNT_POOL) + len(HK_ACCOUNTS) + len(AU_ACCOUNTS)} 個帳號")
    print(f"  └─ 台灣 {len(ACCOUNT_POOL)} / 香港 {len(HK_ACCOUNTS)} / 澳洲二代 {len(AU_ACCOUNTS)}")
    print(f"投票題庫:{len(VOTE_QUESTIONS)} 題")
    print(f"雷達圖題庫:{len(RADAR_TOPICS)} 場")
    print()

    # 讀歷史
    print("──────── 讀取歷史 ────────")
    history_articles = load_articles_history()
    print()

    new_articles = []
    used_topics = set()
    used_source_ids = set()

    # 四版主各產 1 篇討論 + 1 篇原創
    for persona_name, persona in PERSONAS.items():
        print(f"────────  {persona_name}({persona['domain']})  ────────")

        # D 類:討論型(Reddit/HN 素材)
        print(f"  [1/2] 討論型文章...")
        material = gather_persona_material(persona_name, persona)
        material = [p for p in material if p["id"] not in used_source_ids]

        article_d = None
        if material:
            top_post = material[0]
            used_source_ids.add(top_post["id"])
            source_label = top_post.get("source", "").upper()
            print(f"        素材:{top_post['title'][:50]}({source_label} +{top_post['score']})")
            if top_post.get("source") == "hn":
                comments_raw = fetch_hn_comments(top_post["id"], limit=5)
            elif top_post.get("source") == "reddit":
                comments_raw = fetch_reddit_comments(top_post["id"], top_post.get("subreddit",""), limit=5)
            else:
                comments_raw = []
            print(f"        抓到 {len(comments_raw)} 條回覆")
            article_d = generate_discussion_article(persona_name, persona, top_post, comments_raw)

        if article_d:
            print(f"        ✓ {article_d['title'][:40]}")
            article_d["comments"] = generate_comments(article_d, persona)
            print(f"        ✓ {len(article_d['comments'])} 條評論")
            new_articles.append(article_d)
        else:
            print(f"        ✗ 無素材,回退到原創")
            article_fallback = generate_original_article(persona_name, persona, used_topics)
            if article_fallback:
                used_topics.add(article_fallback.get("topic_used", ""))
                print(f"        ✓(fallback){article_fallback['title'][:40]}")
                article_fallback["comments"] = generate_comments(article_fallback, persona)
                new_articles.append(article_fallback)

        # B 類:原創型
        print(f"  [2/2] 原創型文章...")
        article_b = generate_original_article(persona_name, persona, used_topics)
        if article_b:
            used_topics.add(article_b.get("topic_used", ""))
            print(f"        ✓ {article_b['title'][:40]}")
            article_b["comments"] = generate_comments(article_b, persona)
            print(f"        ✓ {len(article_b['comments'])} 條評論")
            new_articles.append(article_b)
        print()
        time.sleep(60)

    # 納斯達坑:每週一觸發一場(雷達圖)
    today_weekday = datetime.now().weekday()  # 0=週一
    if today_weekday == 0:
        print(f"────────  納斯達坑(週一一場)  ────────")
        naspit_state = load_naspit_state()
        naspit_article, naspit_state = generate_naspit_article(naspit_state)
        if naspit_article:
            naspit_article["comments"] = generate_comments(
                naspit_article, PERSONAS[naspit_article["persona"]]
            )
            new_articles.append(naspit_article)
            save_naspit_state(naspit_state)
            print(f"        ✓ 第{naspit_state['round']}場:{naspit_article['title'][:40]}")
        else:
            print(f"        ✗ 生成失敗")
        print()

    # YouTube 抓取
    print(f"────────  Leek Factory(YouTube)  ────────")
    leek_videos = fetch_youtube_videos(max_results=50)
    print()

    # 合併歷史 + 新文章
    print("──────── 合併歷史與新文章 ────────")
    print(f"  本次新生成:{len(new_articles)} 篇")
    print(f"  歷史累積:{len(history_articles)} 篇")
    all_articles = new_articles + history_articles
    print(f"  合計:{len(all_articles)} 篇")
    save_articles_history(all_articles)
    print()

    # Fowlplay 票數每日累加 + 名人堂檢查
    fowlplay_data = load_fowlplay_data()
    fowlplay_data = daily_vote_increment(fowlplay_data)
    fowlplay_data = check_champions_and_rotate(fowlplay_data)
    save_fowlplay_data(fowlplay_data)
    print(f"  [Fowlplay] 票數已更新,active_slots:{fowlplay_data['active_slots']}")

    # 生成 index.html
    print(f"  生成 index.html...")
    html_content = generate_html(all_articles, videos=leek_videos, new_articles=new_articles)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  ✓ index.html 完成({len(html_content):,} 字元)")

    # SEO 靜態化
    print()
    print("──────── SEO 靜態化 ────────")
    seo_articles = []
    for a in all_articles:
        if not a:
            continue
        a_copy = dict(a)
        if a_copy.get("type") == "naspit":
            a_copy["cat"] = "naspit"
        else:
            a_copy["cat"] = PERSONA_TO_CAT.get(a_copy.get("persona", ""), "salon")
        a_copy["prefix"] = {
            "discussion": "觀察",
            "original": "原創",
            "monitor": "觀察",
            "naspit": "測評",
        }.get(a_copy.get("type", ""), "觀察")
        ensure_article_slug(a_copy)
        for orig in all_articles:
            if orig is a:
                orig["slug"] = a_copy["slug"]
        seo_articles.append(a_copy)

    print(f"  [靜態化] 寫入 {len(seo_articles)} 篇...")
    written = write_static_articles(seo_articles)
    print(f"  [靜態化] ✓ 成功 {len(written)} 篇")

    print(f"  [sitemap] 生成中...")
    sitemap_xml = generate_sitemap_xml(seo_articles)
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_xml)
    print(f"  [sitemap] ✓ {len(written) + 1} 個 URL")

    print(f"  [robots] 生成中...")
    with open("robots.txt", "w", encoding="utf-8") as f:
        f.write(generate_robots_txt())
    print(f"  [robots] ✓")

    save_articles_history(all_articles)

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"  總耗時:{duration}")
    print(f"========================================")


if __name__ == "__main__":
    main()
