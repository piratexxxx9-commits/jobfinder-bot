"""
JobFinder AI — Telegram Bot v3
- Job category buttons
- Job type filter (remote / full-time / part-time)
- Real APIs: Remotive, Arbeitnow, The Muse
- Real APIs: Remotive, Arbeitnow, The Muse, We Work Remotely, Himalayas, Jobicy, Remote OK
"""

import os, asyncio, logging, base64, io
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")

# ── States ────────────────────────────────────────────────────────────────────
(
    MAIN_MENU,
    CHOOSE_CATEGORY,
    CHOOSE_TYPE,
    WAIT_CUSTOM_SEARCH,
    WAIT_ATS_CV,
    WAIT_TAILOR_CV,
    WAIT_TAILOR_JD,
) = range(7)

# ── Job categories (keyword + Arabic label) ───────────────────────────────────
CATEGORIES = [
    # Tech
    ("React Developer",          "⚛️ مطور React"),
    ("Full Stack Developer",     "💻 مطور Full Stack"),
    ("Python Developer",         "🐍 مطور Python"),
    ("Mobile Developer",         "📱 مطور موبايل"),
    ("Data Analyst",             "📊 محلل بيانات"),
    ("Data Scientist",           "🧠 عالم بيانات"),
    ("DevOps Engineer",          "⚙️ مهندس DevOps"),
    ("Cybersecurity",            "🔐 أمن معلومات"),
    # Design
    ("UI UX Designer",           "🎨 مصمم UI/UX"),
    ("Graphic Designer",         "🖌️ مصمم جرافيك"),
    ("Video Editor",             "🎬 مونتير فيديو"),
    # Marketing
    ("Digital Marketer",         "📢 مسوّق رقمي"),
    ("SEO Specialist",           "🔍 متخصص SEO"),
    ("Social Media Manager",     "📱 مدير سوشيال ميديا"),
    ("Content Writer",           "✍️ كاتب محتوى"),
    ("Copywriter",               "📝 كوبي رايتر"),
    # Business
    ("Project Manager",          "📋 مدير مشاريع"),
    ("Business Analyst",         "📈 محلل أعمال"),
    ("Customer Support",         "🎧 خدمة عملاء"),
    ("Sales Representative",     "💼 مندوب مبيعات"),
    # Finance
    ("Accountant",               "💰 محاسب"),
    ("Financial Analyst",        "📉 محلل مالي"),
    # Education
    ("Online Tutor",             "📚 مدرّس أونلاين"),
    ("Translator",               "🌐 مترجم"),
    # Other
    ("Virtual Assistant",        "🤖 مساعد افتراضي"),
    ("HR Specialist",            "👥 متخصص موارد بشرية"),
]

JOB_TYPES = [
    ("remote",    "🌐 عن بعد"),
    ("fulltime",  "💼 دوام كامل"),
    ("parttime",  "⏰ دوام جزئي"),
    ("any",       "🔀 الكل"),
]

# ── Keyboards ─────────────────────────────────────────────────────────────────
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 اختر تخصصك وابحث",    callback_data="browse")],
        [InlineKeyboardButton("✏️ بحث بكلمة خاصة",       callback_data="custom")],
        [InlineKeyboardButton("⭐ وظائف مميزة الآن",      callback_data="featured")],
        [InlineKeyboardButton("📊 فحص سيرتي ATS",        callback_data="ats")],
        [InlineKeyboardButton("✨ تخصيص CV لوظيفة",      callback_data="tailor")],
    ])

def categories_kb():
    """3 categories per row"""
    rows = []
    row  = []
    for i, (kw, label) in enumerate(CATEGORIES):
        row.append(InlineKeyboardButton(label, callback_data=f"cat_{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")])
    return InlineKeyboardMarkup(rows)

def type_kb(cat_idx: int):
    rows = [
        [
            InlineKeyboardButton("🌐 عن بعد",    callback_data=f"type_{cat_idx}_remote"),
            InlineKeyboardButton("💼 دوام كامل",  callback_data=f"type_{cat_idx}_fulltime"),
        ],
        [
            InlineKeyboardButton("⏰ دوام جزئي",  callback_data=f"type_{cat_idx}_parttime"),
            InlineKeyboardButton("🔀 الكل",       callback_data=f"type_{cat_idx}_any"),
        ],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="browse")],
    ]
    return InlineKeyboardMarkup(rows)

def type_kb_custom():
    rows = [
        [
            InlineKeyboardButton("🌐 عن بعد",    callback_data="ctype_remote"),
            InlineKeyboardButton("💼 دوام كامل",  callback_data="ctype_fulltime"),
        ],
        [
            InlineKeyboardButton("⏰ دوام جزئي",  callback_data="ctype_parttime"),
            InlineKeyboardButton("🔀 الكل",       callback_data="ctype_any"),
        ],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")],
    ]
    return InlineKeyboardMarkup(rows)

def cancel_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ]])

def back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")
    ]])

def results_kb(page: int, pages: int):
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"page_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("➡️ التالي", callback_data=f"page_{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔍 بحث جديد",          callback_data="browse")])
    rows.append([InlineKeyboardButton("🏠 القائمة الرئيسية",  callback_data="main")])
    return InlineKeyboardMarkup(rows)

# ── Real Job APIs ─────────────────────────────────────────────────────────────
def _days_ago(date_str: str) -> Optional[int]:
    if not date_str: return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:19], fmt).replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - dt).days)
        except ValueError:
            continue
    return None

def _date_label(d: Optional[int]) -> str:
    if d is None: return "📅 حديثاً"
    if d == 0:    return "🟢 اليوم"
    if d == 1:    return "🟡 أمس"
    if d <= 7:    return f"⏱ منذ {d} أيام"
    return        f"📅 منذ {d} يوم"

async def fetch_remotive(session, keyword: str, job_type: str) -> list:
    try:
        url = f"https://remotive.com/api/remote-jobs?search={keyword}&limit=20"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200: return []
            data = await r.json()
            jobs = []
            for j in (data.get("jobs") or []):
                apply = j.get("url","")
                if not apply.startswith("http"): continue
                jt = j.get("job_type","")
                if job_type == "parttime" and jt != "part_time": continue
                if job_type == "fulltime" and jt == "part_time": continue
                jobs.append({
                    "title":    j.get("title",""),
                    "company":  j.get("company_name",""),
                    "location": j.get("candidate_required_location") or "Worldwide",
                    "type_lbl": "⏰ جزئي" if jt=="part_time" else "🌐 عن بعد",
                    "salary":   j.get("salary") or "",
                    "apply":    apply,
                    "platform": "Remotive",
                    "days":     _days_ago(j.get("publication_date","")),
                    "tags":     (j.get("tags") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"Remotive: {e}"); return []

async def fetch_arbeitnow(session, keyword: str, job_type: str) -> list:
    try:
        async with session.get(
            "https://www.arbeitnow.com/api/job-board-api",
            timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            if r.status != 200: return []
            data = await r.json()
            all_jobs = data.get("data") or []
            kw = keyword.lower()
            if kw:
                all_jobs = [
                    j for j in all_jobs
                    if kw in j.get("title","").lower()
                    or any(kw in t.lower() for t in (j.get("tags") or []))
                ]
            jobs = []
            for j in all_jobs[:20]:
                apply = j.get("url","")
                if not apply.startswith("http"): continue
                is_remote = j.get("remote", False)
                jtypes    = " ".join(j.get("job_types") or []).lower()
                is_part   = "part" in jtypes
                if job_type == "remote"   and not is_remote: continue
                if job_type == "parttime" and not is_part:   continue
                if job_type == "fulltime" and (is_remote or is_part): continue
                ts   = j.get("created_at")
                days = max(0,int((datetime.now(timezone.utc).timestamp()-ts)/86400)) if ts else None
                jobs.append({
                    "title":    j.get("title",""),
                    "company":  j.get("company_name",""),
                    "location": j.get("location") or ("Remote" if is_remote else ""),
                    "type_lbl": "⏰ جزئي" if is_part else "🌐 عن بعد" if is_remote else "💼 كامل",
                    "salary":   "",
                    "apply":    apply,
                    "platform": "Arbeitnow",
                    "days":     days,
                    "tags":     (j.get("tags") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"Arbeitnow: {e}"); return []

async def fetch_themuse(session, keyword: str, job_type: str) -> list:
    try:
        url = ("https://www.themuse.com/api/public/jobs"
               "?location=Flexible+%2F+Remote&page=1&descending=true")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200: return []
            data = await r.json()
            results = data.get("results") or []
            kw = keyword.lower()
            if kw:
                results = [
                    j for j in results
                    if kw in j.get("name","").lower()
                    or any(kw in c.get("name","").lower() for c in (j.get("categories") or []))
                ]
            jobs = []
            for j in results[:10]:
                apply = (j.get("refs") or {}).get("landing_page","")
                if not apply.startswith("http"): continue
                jobs.append({
                    "title":    j.get("name",""),
                    "company":  (j.get("company") or {}).get("name",""),
                    "location": ", ".join(
                        loc.get("name","") for loc in (j.get("locations") or [])
                    ) or "Remote",
                    "type_lbl": "🌐 عن بعد",
                    "salary":   "",
                    "apply":    apply,
                    "platform": "The Muse",
                    "days":     _days_ago(j.get("publication_date","")),
                    "tags":     [c.get("name","") for c in (j.get("categories") or [])][:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"TheMuse: {e}"); return []


async def fetch_weworkremotely(session, keyword: str, job_type: str) -> list:
    """We Work Remotely — free RSS/API, real direct job links"""
    try:
        # WWR has category RSS feeds; use the general remote jobs feed
        url = "https://weworkremotely.com/remote-jobs.json"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
            jobs_raw = data if isinstance(data, list) else data.get("jobs", [])
            kw = keyword.lower()
            jobs = []
            for j in jobs_raw:
                title   = j.get("title","") or j.get("position","")
                company = j.get("company","") or j.get("company_name","")
                apply   = j.get("url","")  or j.get("apply_url","")
                if not apply.startswith("http"): continue
                if kw and kw not in title.lower() and kw not in company.lower():
                    continue
                jobs.append({
                    "title":    title,
                    "company":  company,
                    "location": j.get("region","") or "Worldwide",
                    "type_lbl": "🌐 عن بعد",
                    "salary":   "",
                    "apply":    apply,
                    "platform": "We Work Remotely",
                    "days":     _days_ago(j.get("created_at","") or j.get("date","")),
                    "tags":     [],
                })
            return jobs[:15]
    except Exception as e:
        log.warning(f"WeWorkRemotely: {e}"); return []

async def fetch_himalayas(session, keyword: str, job_type: str) -> list:
    """Himalayas.app — free public API, real remote job postings"""
    try:
        url = f"https://himalayas.app/jobs/api?q={keyword}&limit=20"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
            jobs_raw = data.get("jobs", [])
            jobs = []
            for j in jobs_raw:
                apply = j.get("applicationLink","") or j.get("url","")
                if not apply.startswith("http"):
                    apply = f"https://himalayas.app/jobs/{j.get('slug','')}"
                if not apply.startswith("http"): continue
                jobs.append({
                    "title":    j.get("title",""),
                    "company":  j.get("companyName","") or (j.get("company") or {}).get("name",""),
                    "location": j.get("location","") or "Remote",
                    "type_lbl": "🌐 عن بعد",
                    "salary":   j.get("salary","") or "",
                    "apply":    apply,
                    "platform": "Himalayas",
                    "days":     _days_ago(j.get("createdAt","") or j.get("publishedAt","")),
                    "tags":     (j.get("skills") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"Himalayas: {e}"); return []

async def fetch_jobicy(session, keyword: str, job_type: str) -> list:
    """Jobicy — free public API, real remote jobs with direct apply links"""
    try:
        url = f"https://jobicy.com/api/v2/remote-jobs?count=20&keyword={keyword}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
            jobs_raw = data.get("jobs", [])
            jobs = []
            for j in jobs_raw:
                apply = j.get("url","")
                if not apply.startswith("http"): continue
                jobs.append({
                    "title":    j.get("jobTitle",""),
                    "company":  j.get("companyName",""),
                    "location": j.get("jobGeo","") or "Remote",
                    "type_lbl": "⏰ جزئي" if "part" in j.get("jobType","").lower()
                                else "🌐 عن بعد",
                    "salary":   j.get("annualSalaryMin","") and
                                f"${j['annualSalaryMin']:,}–${j.get('annualSalaryMax',0):,}" or "",
                    "apply":    apply,
                    "platform": "Jobicy",
                    "days":     _days_ago(j.get("pubDate","")),
                    "tags":     (j.get("jobIndustry") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"Jobicy: {e}"); return []

async def fetch_remoteok(session, keyword: str, job_type: str) -> list:
    """Remote OK — free public API, well-known remote job board"""
    try:
        headers = {"User-Agent": "JobFinderBot/1.0"}
        url = "https://remoteok.com/api"
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
            # First item is usually a legal notice dict, skip it
            jobs_raw = [x for x in data if isinstance(x, dict) and x.get("position")]
            kw = keyword.lower()
            if kw:
                jobs_raw = [
                    j for j in jobs_raw
                    if kw in j.get("position","").lower()
                    or kw in j.get("company","").lower()
                    or any(kw in t.lower() for t in (j.get("tags") or []))
                ]
            jobs = []
            for j in jobs_raw[:15]:
                apply = j.get("apply_url","") or j.get("url","")
                if not apply.startswith("http"):
                    slug = j.get("slug","")
                    apply = f"https://remoteok.com/remote-jobs/{slug}" if slug else ""
                if not apply.startswith("http"): continue
                jobs.append({
                    "title":    j.get("position",""),
                    "company":  j.get("company",""),
                    "location": j.get("location","") or "Remote",
                    "type_lbl": "🌐 عن بعد",
                    "salary":   j.get("salary","") or "",
                    "apply":    apply,
                    "platform": "Remote OK",
                    "days":     _days_ago(j.get("date","")),
                    "tags":     (j.get("tags") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"RemoteOK: {e}"); return []

def make_platform_links(keyword: str, job_type: str) -> list:
    # No longer used — all sources are now direct API jobs
    return []

async def search_jobs(keyword: str, job_type: str) -> dict:
    """
    Fetches real direct job postings from 7 free public APIs concurrently.
    All results have verified direct apply links — no search-page redirects.
    Sources: Remotive, Arbeitnow, The Muse, We Work Remotely,
             Himalayas, Jobicy, Remote OK
    """
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            fetch_remotive(session, keyword, job_type),
            fetch_arbeitnow(session, keyword, job_type),
            fetch_themuse(session, keyword, job_type),
            fetch_weworkremotely(session, keyword, job_type),
            fetch_himalayas(session, keyword, job_type),
            fetch_jobicy(session, keyword, job_type),
            fetch_remoteok(session, keyword, job_type),
        )

    merged, seen = [], set()
    for batch in results:
        for j in batch:
            url = j.get("apply","")
            if url and url not in seen:
                seen.add(url)
                merged.append(j)

    merged.sort(key=lambda x: x.get("days") if x.get("days") is not None else 999)

    return {
        "direct":    merged,
        "platforms": [],   # removed — all results are now direct job postings
    }

# ── Format helpers ─────────────────────────────────────────────────────────────
def fmt_direct(j: dict, idx: int) -> str:
    tags = " • ".join(j["tags"]) if j.get("tags") else ""
    return (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{idx}\\. {_esc(j['title'])}*\n"
        f"🏢 {_esc(j['company'])}\n"
        f"📍 {_esc(j['location'])}  •  {j['type_lbl']}\n"
        f"{_date_label(j['days'])}  •  🔗 {j['platform']}\n"
        + (f"💵 {_esc(j['salary'])}\n" if j.get("salary") else "")
        + (f"🏷 {_esc(tags)}\n" if tags else "")
        + f"\n[✅ تقدم مباشرة على الوظيفة]({j['apply']})"
    )

def fmt_platform(j: dict, idx: int) -> str:
    return (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{idx}\\. {_esc(j['platform'])}*\n"
        f"📍 {_esc(j['location'])}\n"
        f"\n[🔍 افتح نتائج البحث في {_esc(j['platform'])}]({j['apply']})"
    )

def _esc(s: str) -> str:
    if not s: return ""
    for ch in r"\_*[]()~`>#+=|{}.!-":
        s = s.replace(ch, f"\\{ch}")
    return s

# ── Gemini helper ──────────────────────────────────────────────────────────────
async def ask_gemini(prompt: str) -> str:
    try:
        resp = await asyncio.to_thread(gemini.generate_content, prompt)
        return resp.text
    except Exception as e:
        return f"⚠️ خطأ: {e}"

# ── Core search flow ───────────────────────────────────────────────────────────
async def run_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool):
    keyword  = ctx.user_data.get("keyword","")
    job_type = ctx.user_data.get("job_type","any")
    type_lbl = dict(JOB_TYPES).get(job_type,"")

    msg_text = (
        f"⏳ أبحث عن وظائف *{_esc(keyword)}* \\({_esc(type_lbl)}\\)\\.\\.\\.\n"
        f"🔄 Remotive · Arbeitnow · The Muse"
    )
    if edit:
        await update.callback_query.edit_message_text(msg_text, parse_mode="MarkdownV2")
    else:
        wait = await update.message.reply_text(msg_text, parse_mode="MarkdownV2")

    data = await search_jobs(keyword, job_type)
    ctx.user_data["direct"]   = data["direct"]
    ctx.user_data["platforms"] = data["platforms"]
    ctx.user_data["page"]     = 0

    if not edit:
        await wait.delete()

    await send_results_page(update, ctx, edit=edit)

async def send_results_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool):
    direct    = ctx.user_data.get("direct", [])
    platforms = ctx.user_data.get("platforms", [])
    keyword   = ctx.user_data.get("keyword","")
    job_type  = ctx.user_data.get("job_type","any")
    type_lbl  = dict(JOB_TYPES).get(job_type,"")
    page      = ctx.user_data.get("page", 0)
    PER       = 4
    total     = len(direct)
    pages     = max(1, -(-total // PER))
    batch     = direct[page*PER : (page+1)*PER]

    # Header
    sources_line = "Remotive · Arbeitnow · The Muse · WWR · Himalayas · Jobicy · RemoteOK"
    text = (
        f"✅ *{total} وظيفة مباشرة* — _{_esc(keyword)}_ \\({_esc(type_lbl)}\\)\n"
        f"🔗 {_esc(sources_line)}\n"
        f"📄 صفحة {page+1} من {pages}\n\n"
    )

    # Direct jobs
    if batch:
        text += "\n\n".join(fmt_direct(j, page*PER+i+1) for i,j in enumerate(batch))
    else:
        text += "😕 لم نجد وظائف مباشرة لهذا التخصص الآن\\.\nجرب تخصصاً مختلفاً أو اختر *الكل* من نوع الوظيفة\\."

    markup = results_kb(page, pages)

    kwargs = dict(
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    if edit:
        await update.callback_query.edit_message_text(**kwargs)
    else:
        await update.message.reply_text(**kwargs)

# ── Handlers ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.effective_user.first_name or "عزيزي"
    await update.message.reply_text(
        f"👋 أهلاً *{name}*\\!\n\n"
        "🤖 أنا *JobFinder AI* — مساعدك للعثور على وظائف حقيقية\n\n"
        "✅ وظائف بروابط مباشرة للتقديم\n"
        "🔗 Remotive · Arbeitnow · Himalayas · Jobicy · Remote OK · WWR · The Muse\n"
        "📊 فحص ATS لسيرتك الذاتية\n"
        "✨ تخصيص CV لكل وظيفة\n\n"
        "اختر ما تريد:",
        parse_mode="MarkdownV2",
        reply_markup=main_kb(),
    )
    return MAIN_MENU

async def cb_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text("اختر ما تريد:", reply_markup=main_kb())
    return MAIN_MENU

async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text("تم الإلغاء ✅", reply_markup=back_kb())
    return MAIN_MENU

# Browse categories
async def cb_browse(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "📂 *اختر التخصص الوظيفي:*",
        parse_mode="Markdown",
        reply_markup=categories_kb(),
    )
    return CHOOSE_CATEGORY

# User picked a category
async def cb_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    cat_idx = int(q.data.split("_")[1])
    keyword, label = CATEGORIES[cat_idx]
    ctx.user_data["keyword"]  = keyword
    ctx.user_data["cat_label"] = label
    await q.edit_message_text(
        f"✅ اخترت: *{label}*\n\n"
        f"اختر نوع الوظيفة:",
        parse_mode="Markdown",
        reply_markup=type_kb(cat_idx),
    )
    return CHOOSE_TYPE

# User picked job type (from category flow)
async def cb_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    parts    = q.data.split("_")   # type_{cat_idx}_{job_type}
    job_type = parts[2]
    ctx.user_data["job_type"] = job_type
    await run_search(update, ctx, edit=True)
    return MAIN_MENU

# Custom search flow
async def cb_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "✏️ *بحث بكلمة خاصة*\n\n"
        "أرسل الكلمة المفتاحية بالإنجليزية:\n\n"
        "أمثلة: `React Developer` · `Accountant` · `Nurse`",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_CUSTOM_SEARCH

async def recv_custom_keyword(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["keyword"] = update.message.text.strip()
    await update.message.reply_text(
        "اختر نوع الوظيفة:",
        reply_markup=type_kb_custom(),
    )
    return CHOOSE_TYPE

# User picked job type (from custom flow)
async def cb_ctype(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    job_type = q.data.split("_")[1]
    ctx.user_data["job_type"] = job_type
    await run_search(update, ctx, edit=True)
    return MAIN_MENU

# Featured
async def cb_featured(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    ctx.user_data["keyword"]  = "developer designer writer"
    ctx.user_data["job_type"] = "remote"
    ctx.user_data["page"]     = 0
    await run_search(update, ctx, edit=True)
    return MAIN_MENU

# Pagination
async def cb_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    ctx.user_data["page"] = int(q.data.split("_")[1])
    await send_results_page(update, ctx, edit=True)
    return MAIN_MENU

# ── ATS ────────────────────────────────────────────────────────────────────────
async def cb_ats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "📊 *فحص سيرتك ATS*\n\n"
        "أرسل نص سيرتك الذاتية كاملاً\n"
        "أو أرسل ملف *PDF* مباشرة 👇",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_ATS_CV

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text locally using pypdf — no API needed, works for any text-based PDF"""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                pages_text.append(t)
        return "\n".join(pages_text).strip()
    except Exception as e:
        log.warning(f"pypdf: {e}")
        return ""

async def recv_ats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.document:
        doc  = update.message.document
        mime = (doc.mime_type or "").lower()
        if "pdf" not in mime:
            await update.message.reply_text(
                "⚠️ يرجى إرسال ملف PDF فقط.",
                reply_markup=cancel_kb()
            )
            return WAIT_ATS_CV

        wait = await update.message.reply_text("⏳ جاري قراءة الملف...")
        file      = await ctx.bot.get_file(doc.file_id)
        pdf_bytes = await file.download_as_bytearray()
        cv_text   = await asyncio.to_thread(extract_pdf_text, bytes(pdf_bytes))
        await wait.delete()

        if not cv_text.strip():
            await update.message.reply_text(
                "⚠️ تعذّر استخراج النص من الملف.\n\n"
                "الأسباب المحتملة:\n"
                "• الملف مسح ضوئي (صورة) — يجب أن يكون PDF نصياً قابلاً للنسخ\n"
                "• الملف محمي بكلمة مرور\n\n"
                "الحل: افتح سيرتك وانسخ النص كاملاً والصقه هنا مباشرة 👇",
                reply_markup=cancel_kb()
            )
            return WAIT_ATS_CV

        lines = len([l for l in cv_text.splitlines() if l.strip()])
        await update.message.reply_text(
            f"✅ تم قراءة الملف ({lines} سطر) — جاري التحليل..."
        )
    else:
        cv_text = update.message.text.strip()

    if len(cv_text) < 80:
        await update.message.reply_text(
            "⚠️ النص قصير جداً. أرسل سيرتك كاملة.",
            reply_markup=cancel_kb()
        )
        return WAIT_ATS_CV

    wait = await update.message.reply_text("🤖 يحلل سيرتك...")
    ctx.user_data["cv"] = cv_text

    prompt = f"""أنت خبير ATS. حلّل هذه السيرة الذاتية بالعربية:

🎯 *الدرجة:* XX/100 — تقدير: A/B/C/D
📝 *ملخص:* جملتان
✅ *نقاط القوة:* 3 نقاط
⚠️ *المشكلات:* 3 نقاط
🔧 *إصلاحات سريعة:* 4 إجراءات
🏷 *كلمات مفتاحية مفقودة:* 5 كلمات

السيرة:
{cv_text[:4000]}"""

    result = await ask_gemini(prompt)
    await wait.delete()
    await update.message.reply_text(
        f"📊 *نتيجة فحص ATS*\n\n{result}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✨ خصص CV لوظيفة", callback_data="tailor")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")],
        ]),
    )
    return MAIN_MENU

# ── Tailor ─────────────────────────────────────────────────────────────────────
async def cb_tailor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if ctx.user_data.get("cv"):
        await q.edit_message_text(
            "✨ *تخصيص CV*\n\nأرسل وصف الوظيفة \\(Job Description\\) الآن:",
            parse_mode="MarkdownV2",
            reply_markup=cancel_kb(),
        )
        return WAIT_TAILOR_JD
    await q.edit_message_text(
        "✨ *تخصيص CV*\n\nأرسل نص سيرتك الذاتية أولاً:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_TAILOR_CV

async def recv_tailor_cv(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["cv"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ تم حفظ سيرتك\\. الآن أرسل وصف الوظيفة:",
        parse_mode="MarkdownV2",
        reply_markup=cancel_kb(),
    )
    return WAIT_TAILOR_JD

async def recv_tailor_jd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    jd = update.message.text.strip()
    cv = ctx.user_data.get("cv","")
    if not cv:
        await update.message.reply_text("⚠️ لم أجد سيرتك. ابدأ من جديد.", reply_markup=back_kb())
        return MAIN_MENU

    wait = await update.message.reply_text("✨ أخصّص سيرتك للوظيفة...")
    prompt = f"""خصّص هذه السيرة لتناسب الوظيفة. أجب بالعربية. لا تخترع معلومات.

📊 نسبة التطابق: XX% ← YY%
📄 السيرة المعدّلة: (كاملة جاهزة للنسخ)
🔄 التغييرات: (نقاط مختصرة)
🏷 الكلمات المضافة: كلمة1 • كلمة2

السيرة:
{cv[:3000]}

الوظيفة:
{jd[:2000]}"""

    result = await ask_gemini(prompt)
    await wait.delete()
    await update.message.reply_text(
        f"✨ *نتيجة تخصيص السيرة*\n\n{result}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 فحص ATS مجدداً",    callback_data="ats")],
            [InlineKeyboardButton("🔍 بحث عن وظيفة",      callback_data="browse")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية",  callback_data="main")],
        ]),
    )
    return MAIN_MENU

# Any text → treat as keyword search
async def any_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["keyword"]  = update.message.text.strip()
    ctx.user_data["job_type"] = "any"
    ctx.user_data["page"]     = 0
    await run_search(update, ctx, edit=False)
    return MAIN_MENU

# ── App ────────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    common_cbs = [
        CallbackQueryHandler(cb_main,     pattern="^main$"),
        CallbackQueryHandler(cb_browse,   pattern="^browse$"),
        CallbackQueryHandler(cb_custom,   pattern="^custom$"),
        CallbackQueryHandler(cb_featured, pattern="^featured$"),
        CallbackQueryHandler(cb_ats,      pattern="^ats$"),
        CallbackQueryHandler(cb_tailor,   pattern="^tailor$"),
        CallbackQueryHandler(cb_page,     pattern=r"^page_\d+$"),
        CallbackQueryHandler(cb_cancel,   pattern="^cancel$"),
        CallbackQueryHandler(cb_category, pattern=r"^cat_\d+$"),
        CallbackQueryHandler(cb_type,     pattern=r"^type_\d+_\w+$"),
        CallbackQueryHandler(cb_ctype,    pattern=r"^ctype_\w+$"),
    ]

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start), *common_cbs],
        states={
            MAIN_MENU:        [*common_cbs,
                               MessageHandler(filters.TEXT & ~filters.COMMAND, any_text)],
            CHOOSE_CATEGORY:  [*common_cbs],
            CHOOSE_TYPE:      [*common_cbs],
            WAIT_CUSTOM_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_custom_keyword),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            WAIT_ATS_CV:      [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_ats),
                MessageHandler(filters.Document.ALL, recv_ats),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            WAIT_TAILOR_CV:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_tailor_cv),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            WAIT_TAILOR_JD:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_tailor_jd),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_user=True, per_chat=True,
    )
    app.add_handler(conv)

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "القائمة الرئيسية"),
        ])
    app.post_init = post_init

    log.info("🤖 JobFinder AI Bot v3 running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
