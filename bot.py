"""
JobFinder AI — Telegram Bot
Uses: Google Gemini (free) + Real job APIs (Remotive, Arbeitnow, The Muse)
100% Free — no credit card needed
"""

import os, asyncio, logging, base64
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

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")   # free tier

# ── Conversation states ───────────────────────────────────────────────────────
MAIN_MENU, WAIT_SEARCH, WAIT_ATS_CV, WAIT_TAILOR_CV, WAIT_TAILOR_JD = range(5)

# ── Keyboards ─────────────────────────────────────────────────────────────────
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 بحث عن وظيفة",     callback_data="search")],
        [InlineKeyboardButton("⭐ وظائف مميزة الآن",   callback_data="featured")],
        [InlineKeyboardButton("📊 فحص سيرتي ATS",     callback_data="ats")],
        [InlineKeyboardButton("✨ تخصيص CV لوظيفة",   callback_data="tailor")],
    ])

def cancel_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ]])

def back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")
    ]])

# ── Real Job APIs (free, no CORS on server) ───────────────────────────────────
async def fetch_remotive(session: aiohttp.ClientSession, keyword: str) -> list:
    try:
        url = f"https://remotive.com/api/remote-jobs?search={keyword}&limit=20"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                return []
            data = await r.json()
            jobs = []
            for j in (data.get("jobs") or []):
                apply = j.get("url", "")
                if not apply.startswith("http"):
                    continue
                jobs.append({
                    "title":    j.get("title", ""),
                    "company":  j.get("company_name", ""),
                    "location": j.get("candidate_required_location") or "Worldwide",
                    "type":     "⏰ جزئي" if j.get("job_type") == "part_time" else "🌐 عن بعد",
                    "salary":   j.get("salary") or "",
                    "apply":    apply,
                    "platform": "Remotive",
                    "days":     _days_ago(j.get("publication_date", "")),
                    "tags":     (j.get("tags") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"Remotive: {e}")
        return []

async def fetch_arbeitnow(session: aiohttp.ClientSession, keyword: str) -> list:
    try:
        async with session.get(
            "https://www.arbeitnow.com/api/job-board-api",
            timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            if r.status != 200:
                return []
            data = await r.json()
            all_jobs = data.get("data") or []
            kw = keyword.lower()
            if kw:
                all_jobs = [
                    j for j in all_jobs
                    if kw in j.get("title","").lower()
                    or any(kw in t.lower() for t in (j.get("tags") or []))
                    or kw in j.get("company_name","").lower()
                ]
            jobs = []
            for j in all_jobs[:15]:
                apply = j.get("url","")
                if not apply.startswith("http"):
                    continue
                ts = j.get("created_at")
                days = max(0, int((datetime.now(timezone.utc).timestamp()-ts)/86400)) if ts else None
                jobs.append({
                    "title":    j.get("title",""),
                    "company":  j.get("company_name",""),
                    "location": j.get("location") or ("Remote" if j.get("remote") else ""),
                    "type":     "⏰ جزئي" if "part" in " ".join(j.get("job_types") or []).lower()
                                else "🌐 عن بعد" if j.get("remote") else "💼 كامل",
                    "salary":   "",
                    "apply":    apply,
                    "platform": "Arbeitnow",
                    "days":     days,
                    "tags":     (j.get("tags") or [])[:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"Arbeitnow: {e}")
        return []

async def fetch_themuse(session: aiohttp.ClientSession, keyword: str) -> list:
    try:
        url = ("https://www.themuse.com/api/public/jobs"
               "?location=Flexible+%2F+Remote&page=1&descending=true")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                return []
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
                if not apply.startswith("http"):
                    continue
                jobs.append({
                    "title":    j.get("name",""),
                    "company":  (j.get("company") or {}).get("name",""),
                    "location": ", ".join(
                        loc.get("name","") for loc in (j.get("locations") or [])
                    ) or "Remote",
                    "type":     "🌐 عن بعد",
                    "salary":   "",
                    "apply":    apply,
                    "platform": "The Muse",
                    "days":     _days_ago(j.get("publication_date","")),
                    "tags":     [c.get("name","") for c in (j.get("categories") or [])][:3],
                })
            return jobs
    except Exception as e:
        log.warning(f"TheMuse: {e}")
        return []

def _days_ago(date_str: str) -> Optional[int]:
    if not date_str:
        return None
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
    return f"📅 منذ {d} يوم"

def _fmt_job(j: dict, idx: int) -> str:
    tags = " • ".join(j["tags"]) if j.get("tags") else ""
    return (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{idx}. {j['title']}*\n"
        f"🏢 {j['company']}\n"
        f"📍 {j['location']}  •  {j['type']}\n"
        f"{_date_label(j['days'])}  •  🔗 {j['platform']}\n"
        + (f"💵 {j['salary']}\n" if j.get("salary") else "")
        + (f"🏷 {tags}\n" if tags else "")
        + f"\n[✅ تقدم الآن على الوظيفة]({j['apply']})"
    )

async def search_all(keyword: str) -> list:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            fetch_remotive(session, keyword),
            fetch_arbeitnow(session, keyword),
            fetch_themuse(session, keyword),
        )
    merged, seen = [], set()
    for batch in results:
        for j in batch:
            url = j.get("apply","")
            if url and url not in seen:
                seen.add(url)
                merged.append(j)
    merged.sort(key=lambda x: x.get("days") if x.get("days") is not None else 999)
    return merged

# ── Gemini helper ──────────────────────────────────────────────────────────────
async def ask_gemini(prompt: str) -> str:
    try:
        resp = await asyncio.to_thread(gemini.generate_content, prompt)
        return resp.text
    except Exception as e:
        return f"⚠️ خطأ: {e}"

# ── Handlers ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.effective_user.first_name or "عزيزي"
    await update.message.reply_text(
        f"👋 أهلاً *{name}*\\!\n\n"
        "🤖 أنا *JobFinder AI* — مساعدك لإيجاد وظائف حقيقية عن بعد ودوام جزئي\n\n"
        "✅ روابط مباشرة للتقديم\n"
        "📊 فحص ATS لسيرتك\n"
        "✨ تخصيص CV لكل وظيفة\n\n"
        "اختر ما تريد:",
        parse_mode="Markdown",
        reply_markup=main_kb(),
    )
    return MAIN_MENU

async def cb_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("اختر ما تريد:", reply_markup=main_kb())
    return MAIN_MENU

async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("تم الإلغاء ✅", reply_markup=back_kb())
    return MAIN_MENU

# Search
async def cb_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔍 *بحث عن وظيفة*\n\n"
        "أرسل الكلمة المفتاحية *بالإنجليزية* للحصول على أفضل النتائج:\n\n"
        "أمثلة:\n"
        "• `React Developer`\n"
        "• `Graphic Designer`\n"
        "• `Content Writer`\n"
        "• `Customer Support`\n"
        "• `Data Analyst`",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_SEARCH

async def recv_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    keyword = update.message.text.strip()
    ctx.user_data["keyword"] = keyword
    ctx.user_data["page"]    = 0

    wait = await update.message.reply_text(
        f"⏳ أبحث عن وظائف حقيقية لـ *{keyword}*...\n"
        "🔄 Remotive · Arbeitnow · The Muse",
        parse_mode="Markdown",
    )
    jobs = await search_all(keyword)
    ctx.user_data["jobs"] = jobs
    await wait.delete()

    if not jobs:
        await update.message.reply_text(
            "😕 لم نجد وظائف لهذه الكلمة الآن\\.\n"
            "جرب: `Developer` أو `Designer` أو `Writer`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return MAIN_MENU

    await _send_page(update, ctx, edit=False)
    return MAIN_MENU

async def cb_featured(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer("⏳ جاري التحميل...")
    await q.edit_message_text("⏳ أجلب أفضل الوظائف المتاحة الآن...")
    jobs = await search_all("developer designer writer marketing")
    ctx.user_data["jobs"]    = jobs[:30]
    ctx.user_data["keyword"] = "وظائف مميزة"
    ctx.user_data["page"]    = 0
    if not jobs:
        await q.edit_message_text("😕 لا توجد وظائف الآن، حاول لاحقاً.", reply_markup=back_kb())
        return MAIN_MENU
    await _send_page(update, ctx, edit=True)
    return MAIN_MENU

async def cb_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["page"] = int(q.data.split("_")[1])
    await _send_page(update, ctx, edit=True)
    return MAIN_MENU

async def _send_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool):
    jobs    = ctx.user_data.get("jobs", [])
    kw      = ctx.user_data.get("keyword", "")
    page    = ctx.user_data.get("page", 0)
    PER     = 5
    total   = len(jobs)
    pages   = max(1, -(-total // PER))
    batch   = jobs[page*PER : (page+1)*PER]

    text = (
        f"✅ *{total} وظيفة حقيقية* — _{kw}_\n"
        f"📄 صفحة {page+1} من {pages}\n\n"
        + "\n\n".join(_fmt_job(j, page*PER+i+1) for i,j in enumerate(batch))
    )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"page_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("➡️ التالي", callback_data=f"page_{page+1}"))

    btns = []
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton("🔍 بحث جديد",           callback_data="search")])
    btns.append([InlineKeyboardButton("🏠 القائمة الرئيسية",   callback_data="main")])

    kwargs = dict(
        text=text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(btns),
        disable_web_page_preview=True,
    )
    if edit:
        await update.callback_query.edit_message_text(**kwargs)
    else:
        await update.message.reply_text(**kwargs)

# ATS
async def cb_ats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "📊 *فحص سيرتك ATS*\n\n"
        "أرسل نص سيرتك الذاتية كاملاً هنا\n"
        "أو أرسل ملف *PDF* مباشرة 👇",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_ATS_CV

async def recv_ats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.document:
        doc = update.message.document
        if "pdf" not in (doc.mime_type or ""):
            await update.message.reply_text("⚠️ أرسل ملف PDF فقط.", reply_markup=cancel_kb())
            return WAIT_ATS_CV
        wait = await update.message.reply_text("⏳ أقرأ الملف...")
        file    = await ctx.bot.get_file(doc.file_id)
        pdf_bytes = await file.download_as_bytearray()
        b64     = base64.b64encode(pdf_bytes).decode()
        prompt  = (
            "Extract all text from this PDF CV. "
            "Return only the raw text preserving structure.\n\n"
            f"[PDF base64 content - {len(b64)} chars - process as document]"
        )
        # For Gemini: send as inline data
        try:
            resp = await asyncio.to_thread(
                gemini.generate_content,
                [{"mime_type":"application/pdf","data":pdf_bytes}, "Extract all text from this CV/resume PDF. Return only raw text."]
            )
            cv_text = resp.text
        except Exception:
            cv_text = ""
        await wait.delete()
        if not cv_text.strip():
            await update.message.reply_text(
                "⚠️ تعذّر قراءة الملف. الصق نص سيرتك بدلاً من ذلك.",
                reply_markup=cancel_kb()
            )
            return WAIT_ATS_CV
    else:
        cv_text = update.message.text.strip()

    if len(cv_text) < 80:
        await update.message.reply_text("⚠️ النص قصير جداً. أرسل سيرتك كاملة.", reply_markup=cancel_kb())
        return WAIT_ATS_CV

    wait = await update.message.reply_text("🤖 يحلل سيرتك الذاتية...")
    ctx.user_data["cv"] = cv_text

    prompt = f"""أنت خبير ATS. حلّل هذه السيرة الذاتية وأعط تقريراً باللغة العربية منظماً هكذا:

🎯 *الدرجة:* XX/100 — تقدير: A/B/C/D

📝 *ملخص:* جملتان عن الوضع العام

✅ *نقاط القوة:*
• ...
• ...
• ...

⚠️ *المشكلات:*
• ...
• ...
• ...

🔧 *إصلاحات سريعة:*
1. ...
2. ...
3. ...
4. ...

🏷 *كلمات مفتاحية مفقودة:*
كلمة1 • كلمة2 • كلمة3 • كلمة4 • كلمة5

السيرة:
{cv_text[:4000]}"""

    result = await ask_gemini(prompt)
    await wait.delete()

    await update.message.reply_text(
        f"📊 *نتيجة فحص ATS*\n\n{result}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✨ خصص CV لوظيفة",        callback_data="tailor")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية",     callback_data="main")],
        ]),
    )
    return MAIN_MENU

# Tailor
async def cb_tailor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if ctx.user_data.get("cv"):
        await q.edit_message_text(
            "✨ *تخصيص CV للوظيفة*\n\n"
            "سأستخدم سيرتك المحفوظة من فحص ATS\\.\n\n"
            "أرسل *وصف الوظيفة* \\(Job Description\\) الآن:",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return WAIT_TAILOR_JD
    await q.edit_message_text(
        "✨ *تخصيص CV للوظيفة*\n\n"
        "أرسل نص سيرتك الذاتية أولاً:",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return WAIT_TAILOR_CV

async def recv_tailor_cv(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["cv"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ تم حفظ سيرتك\\.\n\n"
        "الآن أرسل *وصف الوظيفة* \\(Job Description\\):",
        parse_mode="Markdown",
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

    prompt = f"""أنت خبير كتابة سيرة ذاتية. خصّص هذه السيرة لتناسب الوظيفة المطلوبة. أجب بالعربية.

قدّم:

📊 *نسبة التطابق:* XX% ← YY%

📄 *السيرة المعدّلة:*
(اكتب السيرة كاملة جاهزة للنسخ)

🔄 *التغييرات التي أجريتها:*
• ...

🏷 *الكلمات المفتاحية التي أضفتها:*
كلمة1 • كلمة2 • كلمة3

لا تخترع معلومات مزيفة — فقط أعد صياغة ما هو موجود.

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
            [InlineKeyboardButton("📊 فحص ATS مجدداً",       callback_data="ats")],
            [InlineKeyboardButton("🔍 ابحث عن وظيفة",        callback_data="search")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية",     callback_data="main")],
        ]),
    )
    return MAIN_MENU

# Any text = search
async def any_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["keyword"] = update.message.text.strip()
    ctx.user_data["page"]    = 0
    wait = await update.message.reply_text("⏳ أبحث...")
    jobs = await search_all(ctx.user_data["keyword"])
    ctx.user_data["jobs"] = jobs
    await wait.delete()
    if not jobs:
        await update.message.reply_text(
            "😕 لم نجد نتائج. جرب كلمة إنجليزية مثل `Developer`",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return MAIN_MENU
    await _send_page(update, ctx, edit=False)
    return MAIN_MENU

# ── Build App ──────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    handlers_main = [
        CallbackQueryHandler(cb_main,     pattern="^main$"),
        CallbackQueryHandler(cb_search,   pattern="^search$"),
        CallbackQueryHandler(cb_featured, pattern="^featured$"),
        CallbackQueryHandler(cb_ats,      pattern="^ats$"),
        CallbackQueryHandler(cb_tailor,   pattern="^tailor$"),
        CallbackQueryHandler(cb_page,     pattern=r"^page_\d+$"),
        CallbackQueryHandler(cb_cancel,   pattern="^cancel$"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, any_text),
    ]

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            *handlers_main,
        ],
        states={
            MAIN_MENU:      handlers_main,
            WAIT_SEARCH:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_search),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            WAIT_ATS_CV:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_ats),
                MessageHandler(filters.Document.ALL, recv_ats),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            WAIT_TAILOR_CV: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_tailor_cv),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            WAIT_TAILOR_JD: [
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
            BotCommand("start",    "القائمة الرئيسية"),
            BotCommand("help",     "المساعدة"),
        ])

    app.post_init = post_init
    log.info("🤖 JobFinder AI Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
