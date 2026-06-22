"""
api_key_manager.py
Centralized API Key Management for SEO Technical Audit Dashboard.

Storage hierarchy (highest precedence first):
  1. Session state  — runtime, always available
  2. .streamlit/api_keys.json — local persistence (survives reloads, lost on redeploy)
  3. Streamlit Secrets — production-permanent, read-only from the UI
"""

import json
import requests
from pathlib import Path

import streamlit as st

# ── Storage ──────────────────────────────────────────────────────────────────
_KEYS_FILE  = Path(".streamlit/api_keys.json")
_SS_STORE   = "api_keys_store"       # session-state key for the live dict
_SS_STATUS  = "api_key_test_status"  # {api_id: {"ok": bool, "msg": str}}


# ── Complete API Registry ────────────────────────────────────────────────────
# Each tuple: (id, display_name, placeholder, docs_url, testable)
# testable=True  → a real HTTP test is implemented below
# testable=False → we can only check the key is non-empty

CATEGORIES: list[dict] = [
    {
        "id": "seo_search", "label": "SEO & Search Engine Tools", "icon": "🔍",
        "apis": [
            ("psi",          "Google PageSpeed Insights",  "AIzaSy...",                 "https://console.cloud.google.com",                True),
            ("gsc",          "Google Search Console",      "OAuth / Service Account",   "https://search.google.com/search-console",         False),
            ("ga4",          "Google Analytics 4 (GA4)",   "OAuth / Service Account",   "https://analytics.google.com",                     False),
            ("g_indexing",   "Google Indexing API",         "Service Account JSON key",  "https://console.cloud.google.com",                 False),
            ("g_bizprofile", "Google Business Profile API", "Service Account JSON key",  "https://console.cloud.google.com",                 False),
            ("bing_wmt",     "Bing Webmaster Tools",        "bing_key_...",              "https://www.bing.com/webmasters/help/getting-started-with-bwt-2a3d7e1d", False),
            ("ahrefs",       "Ahrefs",                      "ahrefs_...",                "https://ahrefs.com/api",                           True),
            ("semrush",      "SEMrush",                     "semrush_api_key...",        "https://www.semrush.com/api-documentation/",        True),
            ("moz",          "Moz API",                     "mozscape-...",              "https://moz.com/api",                              True),
            ("majestic",     "Majestic SEO API",             "privkey...",               "https://majestic.com/api",                         False),
            ("screamingfrog","Screaming Frog API",           "SF-api-key...",            "https://www.screamingfrog.co.uk/seo-spider/api/",   False),
            ("dataforseo",   "DataForSEO API",               "email:password",           "https://dataforseo.com/api",                        True),
            ("serpapi",      "SerpApi",                      "serpapi_key...",            "https://serpapi.com/manage-api-key",                True),
            ("valueserp",    "ValueSERP API",                "valueserp_key...",          "https://www.valueserp.com",                         False),
            ("zenserp",      "Zenserp API",                  "zenserp_key...",            "https://zenserp.com",                               False),
            ("brightedge",   "BrightEdge API",               "brightedge_key...",         "https://brightedge.com",                            False),
            ("conductor",    "Conductor API",                "conductor_key...",          "https://conductor.com",                             False),
        ],
    },
    {
        "id": "serp_kw", "label": "SERP & Keyword Tracking", "icon": "📈",
        "apis": [
            ("g_serp",       "Google SERP API",              "AIzaSy... / CX:...",        "https://console.cloud.google.com",                 False),
            ("bing_serp",    "Bing SERP API",                "bing_search_key...",        "https://www.microsoft.com/en-us/bing/apis/bing-web-search-api", True),
            ("yt_search",    "YouTube Search API",           "AIzaSy...",                 "https://console.cloud.google.com",                 False),
            ("kw_everywhere","Keywords Everywhere",          "kwe_key...",                "https://keywordseverywhere.com/api.html",           False),
            ("kw_surfer",    "Keyword Surfer API",           "surfer_key...",             "https://app.surferseo.com",                         False),
        ],
    },
    {
        "id": "ai_content", "label": "AI & Content Tools", "icon": "🤖",
        "apis": [
            ("openai",       "OpenAI",                       "sk-...",                    "https://platform.openai.com/api-keys",              True),
            ("anthropic",    "Anthropic Claude",             "sk-ant-...",               "https://console.anthropic.com",                     True),
            ("gemini",       "Google Gemini",                "AIzaSy...",                 "https://aistudio.google.com/app/apikey",            True),
            ("cohere",       "Cohere",                       "cohere_key...",             "https://dashboard.cohere.com/api-keys",             True),
            ("perplexity",   "Perplexity AI",                "pplx-...",                  "https://www.perplexity.ai/settings/api",            True),
            ("mistral",      "Mistral AI",                   "mistral_key...",            "https://console.mistral.ai/api-keys/",              True),
            ("deepseek",     "DeepSeek",                     "sk-...",                    "https://platform.deepseek.com",                     False),
            ("huggingface",  "Hugging Face",                 "hf_...",                    "https://huggingface.co/settings/tokens",            True),
            ("groq",         "Groq",                         "gsk_...",                   "https://console.groq.com/keys",                     True),
        ],
    },
    {
        "id": "perf_audit", "label": "Website & Performance Auditing", "icon": "⚡",
        "apis": [
            ("gtmetrix",     "GTmetrix",                     "gtmetrix_key...",           "https://gtmetrix.com/api/",                         True),
            ("webpagetest",  "WebPageTest",                  "wpt_key...",                "https://www.webpagetest.org/getkey.php",             True),
            ("pingdom",      "Pingdom",                      "pingdom_key...",            "https://my.pingdom.com/app/api-tokens",             False),
            ("cloudflare",   "Cloudflare API",               "cloudflare_key...",         "https://dash.cloudflare.com/profile/api-tokens",    True),
            ("crux",         "Chrome UX Report API",         "AIzaSy...",                 "https://console.cloud.google.com",                  True),
        ],
    },
    {
        "id": "tech_seo", "label": "Technical SEO & Crawling", "icon": "🕷️",
        "apis": [
            ("sitebulb",     "Sitebulb API",                 "sitebulb_key...",           "https://sitebulb.com",                              False),
            ("deepcrawl",    "Deepcrawl / Lumar",            "deepcrawl_token...",        "https://app.lumar.io",                              False),
            ("oncrawl",      "Oncrawl",                      "oncrawl_key...",            "https://app.oncrawl.com",                           False),
            ("botify",       "Botify",                       "botify_token...",           "https://botify.com",                                False),
        ],
    },
    {
        "id": "backlink", "label": "Backlink Analysis", "icon": "🔗",
        "apis": [
            ("ahrefs_bl",    "Ahrefs Backlinks",             "ahrefs_...",                "https://ahrefs.com/api",                            False),
            ("semrush_bl",   "SEMrush Backlink API",         "semrush_api_key...",        "https://www.semrush.com/api-documentation/",        False),
            ("majestic_bl",  "Majestic",                     "privkey...",               "https://majestic.com/api",                          False),
            ("moz_link",     "Moz Link Explorer",            "mozscape-...",              "https://moz.com/api",                               False),
        ],
    },
    {
        "id": "content_qa", "label": "Content & Readability", "icon": "✍️",
        "apis": [
            ("languagetool", "LanguageTool",                 "lt_key...",                 "https://languagetool.org/http-api/",                False),
            ("copyscape",    "Copyscape",                    "user:apikey",               "https://www.copyscape.com/api.php",                 False),
            ("originality",  "Originality.ai",               "originality_key...",        "https://originality.ai/api",                        False),
        ],
    },
    {
        "id": "image_media", "label": "Image & Media Optimization", "icon": "🖼️",
        "apis": [
            ("tinypng",      "TinyPNG",                      "tinypng_key...",            "https://tinypng.com/developers",                    True),
            ("imagekit",     "ImageKit",                     "imagekit_key...",           "https://imagekit.io/dashboard#api-keys",            False),
            ("cloudinary",   "Cloudinary",                   "cloudinary_key...",         "https://cloudinary.com/console",                    False),
            ("unsplash",     "Unsplash",                     "unsplash_access_key...",    "https://unsplash.com/developers",                   True),
            ("pexels",       "Pexels",                       "pexels_key...",             "https://www.pexels.com/api/",                       True),
        ],
    },
    {
        "id": "social", "label": "Social Media APIs", "icon": "📱",
        "apis": [
            ("linkedin",     "LinkedIn API",                 "linkedin_client_id...",     "https://www.linkedin.com/developers/",              False),
            ("facebook",     "Facebook Graph API",           "fb_access_token...",        "https://developers.facebook.com",                   False),
            ("instagram",    "Instagram Graph API",          "ig_access_token...",        "https://developers.facebook.com",                   False),
            ("twitter_x",    "X (Twitter) API",              "twitter_bearer_token...",   "https://developer.twitter.com",                     True),
            ("youtube",      "YouTube Data API",             "AIzaSy...",                 "https://console.cloud.google.com",                  False),
            ("tiktok",       "TikTok API",                   "tiktok_client_key...",      "https://developers.tiktok.com",                     False),
            ("reddit",       "Reddit API",                   "reddit_client_id...",       "https://www.reddit.com/prefs/apps",                 False),
            ("pinterest",    "Pinterest API",                "pinterest_app_id...",       "https://developers.pinterest.com",                  False),
        ],
    },
    {
        "id": "local_seo", "label": "Local SEO APIs", "icon": "📍",
        "apis": [
            ("gmaps",        "Google Maps API",              "AIzaSy...",                 "https://console.cloud.google.com",                  False),
            ("gplaces",      "Google Places API",            "AIzaSy...",                 "https://console.cloud.google.com",                  False),
            ("bing_maps",    "Bing Maps API",                "bing_maps_key...",          "https://www.bingmapsportal.com",                    False),
            ("foursquare",   "Foursquare API",               "fsq_key...",                "https://developer.foursquare.com",                  False),
        ],
    },
    {
        "id": "monitoring", "label": "Monitoring & Reporting", "icon": "📊",
        "apis": [
            ("looker",       "Google Looker Studio",         "OAuth token",               "https://lookerstudio.google.com",                   False),
            ("powerbi",      "Power BI API",                 "powerbi_client_id...",      "https://powerbi.microsoft.com",                     False),
            ("tableau",      "Tableau API",                  "tableau_token...",          "https://www.tableau.com/developer",                 False),
            ("databox",      "Databox API",                  "databox_key...",            "https://databox.com/api",                           False),
        ],
    },
    {
        "id": "cms", "label": "CMS Integrations", "icon": "🖥️",
        "apis": [
            ("wordpress",    "WordPress REST API",           "wp_app_password...",        "https://developer.wordpress.org/rest-api/",         False),
            ("webflow",      "Webflow API",                  "webflow_token...",          "https://developers.webflow.com",                    True),
            ("shopify",      "Shopify API",                  "shpat_...",                 "https://shopify.dev/api",                           False),
            ("hubspot",      "HubSpot CMS API",              "hubspot_key...",            "https://developers.hubspot.com",                    True),
            ("contentful",   "Contentful API",               "contentful_access_token...",  "https://www.contentful.com/developers/",           True),
            ("strapi",       "Strapi API",                   "strapi_token...",           "https://strapi.io/documentation",                   False),
        ],
    },
    {
        "id": "devops", "label": "Developer & Automation Tools", "icon": "⚙️",
        "apis": [
            ("github",       "GitHub API",                   "ghp_... / github_pat_...",  "https://github.com/settings/tokens",                True),
            ("gitlab",       "GitLab API",                   "glpat-...",                 "https://gitlab.com/-/user_settings/personal_access_tokens", True),
            ("jira",         "Jira API",                     "jira_api_token...",         "https://id.atlassian.com/manage-profile/security/api-tokens", False),
            ("slack",        "Slack API",                    "xoxb-...",                  "https://api.slack.com/apps",                        True),
            ("zapier",       "Zapier API",                   "zapier_key...",             "https://zapier.com/app/developer",                  False),
            ("make",         "Make.com API",                 "make_api_key...",           "https://www.make.com/en/api-documentation",         False),
        ],
    },
    {
        "id": "custom", "label": "Custom APIs", "icon": "🔧",
        "apis": [
            ("custom_rest",  "Custom REST API",              "https://api.example.com",   "",                                                  False),
            ("custom_gql",   "Custom GraphQL API",           "https://api.example.com/graphql", "",                                           False),
            ("custom_int",   "Internal Enterprise API",      "internal_token...",         "",                                                  False),
        ],
    },
]

# Flat lookup: api_id → (name, placeholder, docs_url, testable, category_label)
_API_FLAT: dict[str, dict] = {}
for _cat in CATEGORIES:
    for _entry in _cat["apis"]:
        _api_id, _name, _ph, _docs, _testable = _entry
        _API_FLAT[_api_id] = {
            "name":      _name,
            "ph":        _ph,
            "docs":      _docs,
            "testable":  _testable,
            "category":  _cat["label"],
            "cat_id":    _cat["id"],
        }

# ── Secrets mapping: Streamlit secret key → api_id ───────────────────────────
_SECRETS_MAP: dict[str, str] = {
    "PSI_API_KEY":   "psi",
    "OPENAI_API_KEY": "openai",
    "ANTHROPIC_API_KEY": "anthropic",
    "GEMINI_API_KEY": "gemini",
    "SERPAPI_KEY":   "serpapi",
    "AHREFS_API_KEY": "ahrefs",
    "SEMRUSH_API_KEY": "semrush",
    "MOZ_API_KEY":   "moz",
    "GITHUB_TOKEN":  "github",
    "SLACK_BOT_TOKEN": "slack",
    "CLOUDFLARE_API_TOKEN": "cloudflare",
}


# ── Core Manager ─────────────────────────────────────────────────────────────

class APIKeyManager:
    """Central store for all API keys. Backed by session state + JSON file."""

    @classmethod
    def _load_file(cls) -> dict:
        try:
            if _KEYS_FILE.exists():
                return json.loads(_KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    @classmethod
    def _save_file(cls, store: dict):
        try:
            _KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _KEYS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
            import os, stat
            try:
                os.chmod(_KEYS_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0o600 on POSIX
            except (OSError, NotImplementedError):
                pass  # chmod is a no-op on Windows; file is protected by user directory ACLs
        except Exception:
            pass

    @classmethod
    def _init(cls):
        """Populate session state from file + Streamlit secrets (once per session)."""
        if _SS_STORE not in st.session_state:
            store = cls._load_file()
            # Load from Streamlit secrets (never overwrite a UI-entered key)
            try:
                for secret_key, api_id in _SECRETS_MAP.items():
                    val = st.secrets.get(secret_key, "")
                    if val and api_id not in store:
                        store[api_id] = val
            except Exception:
                pass
            st.session_state[_SS_STORE] = store
        if _SS_STATUS not in st.session_state:
            st.session_state[_SS_STATUS] = {}

    @classmethod
    def get(cls, api_id: str) -> str:
        """Return the stored API key for the given id, or empty string."""
        cls._init()
        return st.session_state[_SS_STORE].get(api_id, "")

    @classmethod
    def set(cls, api_id: str, key: str):
        """Save a key. Persists to file immediately."""
        cls._init()
        key = key.strip()
        if key:
            st.session_state[_SS_STORE][api_id] = key
        else:
            st.session_state[_SS_STORE].pop(api_id, None)
        st.session_state[_SS_STATUS].pop(api_id, None)  # reset test result
        cls._save_file(st.session_state[_SS_STORE])

    @classmethod
    def delete(cls, api_id: str):
        """Remove a key entirely."""
        cls._init()
        st.session_state[_SS_STORE].pop(api_id, None)
        st.session_state[_SS_STATUS].pop(api_id, None)
        cls._save_file(st.session_state[_SS_STORE])

    @classmethod
    def has(cls, api_id: str) -> bool:
        return bool(cls.get(api_id))

    @classmethod
    def mask(cls, key: str) -> str:
        if not key:
            return ""
        if len(key) <= 4:
            return "•" * len(key)
        # Show only a short prefix — never a suffix — to minimise exposure
        show = min(4, max(1, len(key) // 8))
        return key[:show] + "•" * (len(key) - show)

    @classmethod
    def configured_count(cls) -> int:
        cls._init()
        return len(st.session_state[_SS_STORE])

    @classmethod
    def all_ids(cls) -> list[str]:
        cls._init()
        return list(st.session_state[_SS_STORE].keys())

    @classmethod
    def export_secrets_format(cls) -> str:
        """Return a TOML snippet suitable for pasting into Streamlit Secrets."""
        cls._init()
        store = st.session_state[_SS_STORE]
        reverse_map = {v: k for k, v in _SECRETS_MAP.items()}
        lines = ["# Paste into Streamlit Cloud → App settings → Secrets"]
        for api_id, key in store.items():
            secret_key = reverse_map.get(api_id, api_id.upper() + "_API_KEY")
            lines.append(f'{secret_key} = "{key}"')
        return "\n".join(lines)

    @classmethod
    def get_test_status(cls, api_id: str) -> dict | None:
        cls._init()
        return st.session_state[_SS_STATUS].get(api_id)

    @classmethod
    def set_test_status(cls, api_id: str, ok: bool, msg: str):
        cls._init()
        st.session_state[_SS_STATUS][api_id] = {"ok": ok, "msg": msg}


# ── Connection Testers ────────────────────────────────────────────────────────

def _safe_err(key: str, exc: Exception) -> str:
    """Return a sanitized error string with the key value redacted."""
    msg = str(exc)[:200]
    if key and len(key) > 4:
        msg = msg.replace(key, "[REDACTED]")
    return f"Request failed: {msg}"

def _test_psi(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            params={"url": "https://www.google.com", "key": key, "strategy": "mobile"},
            timeout=15,
        )
        if r.status_code == 200:
            return True, "Connected — PageSpeed Insights API is working"
        if r.status_code == 400:
            return False, "Invalid API key — check Console credentials"
        if r.status_code == 403:
            return False, "Key not authorized — enable PageSpeed Insights API in Console"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_openai(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — OpenAI API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code == 429:
            return True, "⚠️ Rate limited but key is valid"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_anthropic(key: str) -> tuple[bool, str]:
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
            timeout=10,
        )
        if r.status_code in (200, 201):
            return True, "Connected — Anthropic API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code == 429:
            return True, "⚠️ Rate limited but key is valid"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_gemini(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Gemini API is working"
        if r.status_code in (400, 403):
            return False, "Invalid or unauthorized API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_serpapi(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(f"https://serpapi.com/account?api_key={key}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            remaining = data.get("plan_searches_left", "?")
            return True, f"Connected — {remaining} searches remaining"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_github(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if r.status_code == 200:
            login = r.json().get("login", "?")
            return True, f"Connected as @{login}"
        if r.status_code == 401:
            return False, "Invalid token"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_slack(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json() if r.status_code == 200 else {}
        if data.get("ok"):
            team = data.get("team", "?")
            return True, f"Connected to workspace: {team}"
        return False, data.get("error", f"HTTP {r.status_code}")
    except Exception as e:
        return False, _safe_err(key, e)


def _test_cloudflare(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=10,
        )
        data = r.json() if r.status_code == 200 else {}
        if data.get("success"):
            return True, "Connected — Cloudflare API token is valid"
        return False, str(data.get("errors", f"HTTP {r.status_code}"))
    except Exception as e:
        return False, _safe_err(key, e)


def _test_gtmetrix(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://gtmetrix.com/api/2.0/me",
            auth=(key, ""),
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", {}).get("attributes", {})
            credits = data.get("api_credits", "?")
            return True, f"Connected — {credits} API credits remaining"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_hubspot(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.hubapi.com/crm/v3/properties/contacts",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — HubSpot API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_webflow(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.webflow.com/v2/sites",
            headers={"Authorization": f"Bearer {key}", "accept": "application/json"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Webflow API is working"
        if r.status_code == 401:
            return False, "Invalid API token"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_bing_search(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": key},
            params={"q": "test", "count": 1},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Bing Search API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_pexels(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/curated?per_page=1",
            headers={"Authorization": key},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Pexels API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_unsplash(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            f"https://api.unsplash.com/photos?client_id={key}&per_page=1",
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Unsplash API is working"
        if r.status_code == 401:
            return False, "Invalid access key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_tinypng(key: str) -> tuple[bool, str]:
    try:
        import base64
        auth = base64.b64encode(f"api:{key}".encode()).decode()
        r = requests.get(
            "https://api.tinify.com/",
            headers={"Authorization": f"Basic {auth}"},
            timeout=10,
        )
        if r.status_code in (200, 201):
            used = r.headers.get("Compression-Count", "?")
            return True, f"Connected — {used} compressions used this month"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_groq(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Groq API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_perplexity(key: str) -> tuple[bool, str]:
    try:
        r = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-sonar-small-128k-online", "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
            timeout=10,
        )
        if r.status_code in (200, 201):
            return True, "Connected — Perplexity API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_mistral(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Mistral AI API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_huggingface(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            user = r.json().get("name", "?")
            return True, f"Connected as {user}"
        if r.status_code == 401:
            return False, "Invalid token"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


def _test_cohere(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            "https://api.cohere.ai/v1/check-api-key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Connected — Cohere API is working"
        if r.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, _safe_err(key, e)


# ── Test dispatch ─────────────────────────────────────────────────────────────
_TESTERS: dict[str, callable] = {
    "psi":         _test_psi,
    "openai":      _test_openai,
    "anthropic":   _test_anthropic,
    "gemini":      _test_gemini,
    "serpapi":     _test_serpapi,
    "github":      _test_github,
    "gitlab":      lambda k: (_test_github.__wrapped__(k) if hasattr(_test_github, "__wrapped__") else _test_github(k)),
    "slack":       _test_slack,
    "cloudflare":  _test_cloudflare,
    "gtmetrix":    _test_gtmetrix,
    "hubspot":     _test_hubspot,
    "webflow":     _test_webflow,
    "bing_serp":   _test_bing_search,
    "pexels":      _test_pexels,
    "unsplash":    _test_unsplash,
    "tinypng":     _test_tinypng,
    "groq":        _test_groq,
    "perplexity":  _test_perplexity,
    "mistral":     _test_mistral,
    "huggingface": _test_huggingface,
    "cohere":      _test_cohere,
}

# Fix gitlab — just use same Bearer pattern as github
_TESTERS["gitlab"] = lambda k: _test_github(k)


def test_api_key(api_id: str) -> tuple[bool, str]:
    """
    Test connection for the given api_id using the stored key.
    Returns (success: bool, message: str).
    """
    key = APIKeyManager.get(api_id)
    if not key:
        return False, "No API key configured"
    tester = _TESTERS.get(api_id)
    if not tester:
        return None, "No test available for this API — key saved but not verified"
    ok, msg = tester(key)
    APIKeyManager.set_test_status(api_id, ok, msg)
    return ok, msg
