"""
The FAQ page's questions.

Until the store saves its own list in admin Settings, the storefront shows
DEFAULT_FAQS. They only describe how the shop actually works (checkout,
slots, the delivery PIN, cancellation rules), so they're safe to show as-is.
Keep them in step with that behaviour if it changes.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.faq import FaqItem
from app.schemas.faq import SECTION_LABELS, FaqIn

SECTION_ORDER = list(SECTION_LABELS)

DEFAULT_FAQS: list[dict] = [
    # Ordering
    {"section": "ordering", "question": "Do I need an account to order?",
     "answer": "No. You can check out as a guest with your email and phone number. An account lets you see all your orders in one place, save addresses and reorder in a tap."},
    {"section": "ordering", "question": "Is the meat fresh or frozen?",
     "answer": "Fresh. It's prepared for your order and delivered in the slot you choose."},
    {"section": "ordering", "question": "Can I cancel or change an order?",
     "answer": "If you have an account, you can cancel an order yourself from My orders until it's paid. Once it's paid, or if you ordered as a guest, contact us and we'll help."},
    {"section": "ordering", "question": "Do you take bulk or event orders?",
     "answer": "Yes, for naming ceremonies, weddings, parties and the like. Send us a message from the Contact page with what you need, how much and when, and we'll get back to you."},
    # Delivery
    {"section": "delivery", "question": "Where do you deliver?",
     "answer": "Across Abuja. The areas we cover and the estimated fee for each are listed on this page. If your area isn't there, choose pickup or contact us."},
    {"section": "delivery", "question": "How much is delivery, and how do I pay for it?",
     "answer": "It depends on your area. The fee shown at checkout is an estimate that you pay the courier in cash when your order arrives; it isn't charged online."},
    {"section": "delivery", "question": "When can you deliver?",
     "answer": "You pick a day and a 1-hour slot at checkout: Monday to Saturday 8am–7pm, Sunday 10am–4pm. Same-day slots need at least an hour's notice."},
    {"section": "delivery", "question": "What's the delivery PIN for?",
     "answer": "When your order goes out you get a 4-digit PIN. Give it to the courier only once the order is in your hands. That's how we know it reached you."},
    {"section": "delivery", "question": "Can I collect my order instead?",
     "answer": "Yes. Choose pickup at checkout. It's free, and we'll let you know when your order is ready to collect."},
    {"section": "delivery", "question": "How do I track my order?",
     "answer": "If you're signed in, go to My orders. If you ordered as a guest, use Track order with your order number and the email you used."},
    # Payment
    {"section": "payment", "question": "How can I pay?",
     "answer": "Online through Paystack, or in cash when your order arrives (or when you collect it)."},
    {"section": "payment", "question": "Is paying online safe?",
     "answer": "Yes. Online payments are handled by Paystack; we never see or store your card details."},
    {"section": "payment", "question": "What does my online payment cover?",
     "answer": "Only your items. The delivery fee is paid separately, in cash to the courier."},
    # Account
    {"section": "account", "question": "I forgot my password. What do I do?",
     "answer": "On the sign-in page, choose \"Forgot password?\" and we'll email you a link to set a new one."},
    {"section": "account", "question": "Why should I verify my email?",
     "answer": "So we know order updates and password resets reach you. Use the link we emailed you when you signed up, or ask for a new one from the banner at the top of the site."},
    {"section": "account", "question": "Can I delete my account?",
     "answer": "Yes. Go to Profile → Sign-in & security and choose Delete account. We remove your personal details and saved addresses straight away. We keep a record of past orders, without your details, because the law requires sales records. You can't delete it while you have an order in progress; cancel unpaid ones from My orders, or wait until they're delivered."},
    {"section": "account", "question": "Can I save my delivery addresses?",
     "answer": "Yes. Add them under Profile → Addresses, set one as your default, and pick from them at checkout."},
]


async def _saved(db: AsyncSession) -> list[FaqItem] | None:
    count = (await db.execute(select(func.count(FaqItem.id)))).scalar_one()
    if count == 0:
        return None
    return list((await db.execute(select(FaqItem).order_by(FaqItem.position))).scalars().all())


async def list_public(db: AsyncSession) -> list:
    saved = await _saved(db)
    if saved is None:
        return DEFAULT_FAQS
    return [f for f in saved if f.is_published]


async def list_admin(db: AsyncSession) -> dict:
    saved = await _saved(db)
    if saved is None:
        return {"items": DEFAULT_FAQS, "is_default": True}
    return {"items": saved, "is_default": False}


async def replace_faqs(db: AsyncSession, items: list[FaqIn]) -> list[FaqItem]:
    """Save the whole list, in order. Saved rows missing from `items` are deleted."""
    existing = {f.id: f for f in (await db.execute(select(FaqItem))).scalars().all()}
    kept: set[str] = set()
    for position, item in enumerate(items):
        row = existing.get(item.id) if item.id else None
        if row is None:
            row = FaqItem()
            db.add(row)
        else:
            kept.add(row.id)
        row.section = item.section
        row.question = item.question
        row.answer = item.answer
        row.is_published = item.is_published
        row.position = position
    gone = [i for i in existing if i not in kept]
    if gone:
        await db.execute(delete(FaqItem).where(FaqItem.id.in_(gone)))
    await db.commit()
    return list((await db.execute(select(FaqItem).order_by(FaqItem.position))).scalars().all())
