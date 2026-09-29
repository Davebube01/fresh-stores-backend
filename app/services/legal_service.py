"""
The Terms and Privacy pages.

Until the store saves its own text in admin Settings, the storefront shows the
defaults below. They describe how this shop actually works (checkout, Paystack,
cash on delivery, the delivery PIN, which cookies we set, which details we
keep), so keep them in step if that changes. They're a starting point, not
legal advice: the admin editor says so.

Both the defaults and the store's own text can use placeholders, filled in from
Settings → Store details when the page is shown, so the pages stay right when
those details change: {store_name}, {contact}, {address}.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legal import LegalPage
from app.services.settings_service import get_store_settings

TITLES = {"terms": "Terms of service", "privacy": "Privacy policy"}

# When the default text last changed. Bump it when you edit a default.
DEFAULTS_UPDATED_AT = datetime(2026, 9, 29, tzinfo=timezone.utc)

DEFAULT_TERMS = """\
These terms cover buying from {store_name} through this website. By placing an order or creating an account, you agree to them. Please read them alongside our [privacy policy](/privacy).

## Who we are
{store_name} ({address}) sells fresh goat meat and market produce for delivery and pickup in Abuja.

## Your account
You can order as a guest or with an account. If you create one:
- keep your password to yourself; you're responsible for orders placed from your account
- give us an email address and phone number we can reach you on about your orders
We may suspend an account that's used for fraud or abuse.

## Orders
Placing an order is an offer to buy. We accept it when we confirm the order. We may decline or cancel an order, for example if an item has sold out or we can't deliver to your address. If you've already paid, we'll refund you in full.

Prices are in naira and include everything except the delivery fee. The price you pay is the one shown at checkout.

## Payment
You can pay:
- online through Paystack, when you place the order. We never see or store your card details. An online order that isn't paid within the time shown at checkout is cancelled automatically.
- in cash, when your order arrives or when you collect it.
Your online payment covers your items only.

## Delivery and pickup
We deliver to the areas listed at checkout, in the day and 1-hour slot you choose. The delivery fee shown at checkout is an estimate for your area, and you pay it in cash to the courier when your order arrives.

When your order goes out, we send you a 4-digit delivery PIN. Give it to the courier only once you have your order: giving the PIN confirms that you've received it. Please make sure someone is available at the address during your slot.

If you choose pickup, it's free. We'll tell you when your order is ready to collect.

## Cancelling an order
If you have an account, you can cancel an order yourself from My orders until it's paid. Once it's paid, or if you ordered as a guest, please contact us and we'll do our best to help.

## If something's wrong
Our products are fresh and perishable. If anything is missing, wrong or not up to standard, contact us as soon as you can, ideally on the day you receive it, and we'll put it right with a replacement or a refund where appropriate. Refunds for online payments go back through Paystack to the way you paid.

Nothing in these terms affects your rights under Nigerian consumer protection law, including the Federal Competition and Consumer Protection Act 2018.

## Our responsibility to you
We're responsible for loss you suffer that's a foreseeable result of us breaking these terms or failing to use reasonable care. We're not responsible for loss that isn't foreseeable, or for business losses. As far as the law allows, our total responsibility for an order is limited to what you paid for it.

## Changes to these terms
We may update these terms from time to time. The version on this page when you place an order is the one that applies to it.

## Law
These terms are governed by the laws of the Federal Republic of Nigeria.

## Contact us
Questions about these terms? Contact us {contact}.
"""

DEFAULT_PRIVACY = """\
This policy explains what personal information {store_name} collects when you use this website, why, and the choices you have. We handle your information in line with the Nigeria Data Protection Act 2023.

## Who we are
{store_name}, {address}, is responsible for your personal information. You can reach us {contact}.

## What we collect
- **Account details:** your name, email address, phone number and password. We store the password only in a scrambled (hashed) form that can't be turned back into it.
- **Delivery details:** the addresses you give at checkout or save to your account, and any delivery instructions.
- **Orders:** what you ordered, when, how you chose to pay, the delivery slot and the order's progress.
- **Payments:** when you pay online, Paystack handles your card or bank details. We receive only the payment's reference and whether it succeeded.
- **Messages:** what you send us through the Contact page, with the name, email and phone number you give.
- **Technical details:** the cookies and browser storage described below, and the basic request information any web server records, such as your IP address.

## Why we use it
- to take, prepare, deliver and support your orders, including sending order updates and your delivery PIN
- to run your account: signing you in, email verification and password resets
- to reply when you contact us
- to prevent fraud and keep the store secure
- to keep the business records the law requires, such as sales and tax records
We use your information because it's needed to fulfil your order or run your account, because the law requires it, or because we have a legitimate interest in running a safe, working store. We don't send marketing emails.

## Who we share it with
We never sell your information. We share it only as far as needed with:
- **Paystack,** to take online payments
- **the courier delivering your order,** who gets your name, phone number, delivery address, delivery instructions and the amount to collect in cash
- **the companies that host this website and send our emails,** who handle it only on our instructions
- **authorities,** where the law requires it

## Cookies and browser storage
We use only what the store needs to work. We don't use advertising or tracking cookies.
- a cookie that keeps you signed in
- a cookie that links a guest's cart to their visit
- your browser's local storage, to remember your cart and checkout details on your device

## How long we keep it
- account details: while your account is open. When you delete it, they're removed straight away.
- orders and payment records: as long as the law requires us to keep business and tax records
- messages: as long as we need them to deal with your request
- sign-in sessions: they expire, and signing out ends them

## Your rights
Under the Nigeria Data Protection Act you can:
- ask for a copy of the information we hold about you
- correct it. You can update your name, phone number and addresses yourself in your [profile](/profile).
- delete your account. You can do this yourself under Profile → Sign-in & security: we remove your personal details and saved addresses, and keep only a record of past orders, without your details, because the law requires sales records.
- object to how we use it, or withdraw consent you've given
To use any of these rights, contact us {contact}. If you're unhappy with how we've handled your information, you can complain to the Nigeria Data Protection Commission.

## Keeping it safe
Our website uses an encrypted (HTTPS) connection, passwords are hashed, and only staff who need your details to handle your order can see them.

## Children
Our store is for adults. We don't knowingly collect information from anyone under 18.

## Changes to this policy
If we change this policy, we'll update it on this page and change the date at the top.
"""

DEFAULTS = {"terms": DEFAULT_TERMS, "privacy": DEFAULT_PRIVACY}


def _fill(body: str, store) -> str:
    ways = []
    if store.contact_email:
        ways.append(f"by email at [{store.contact_email}](mailto:{store.contact_email})")
    if store.contact_phone:
        ways.append(f"by phone on {store.contact_phone}")
    ways.append("through our [Contact page](/contact)")
    contact = ", ".join(ways[:-1]) + (" or " if len(ways) > 1 else "") + ways[-1]
    values = {
        "store_name": store.store_name or "Everything Fresh",
        "contact": contact,
        "address": store.address or "Abuja, Nigeria",
    }
    # Plain replace, not str.format: a stray brace in the store's text mustn't break the page.
    for key, value in values.items():
        body = body.replace("{" + key + "}", value)
    return body


async def get_public_page(db: AsyncSession, slug: str) -> dict:
    row = await db.get(LegalPage, slug)
    store = await get_store_settings(db)
    return {
        "slug": slug,
        "title": TITLES[slug],
        "body": _fill(row.body if row else DEFAULTS[slug], store),
        "updated_at": row.updated_at if row else DEFAULTS_UPDATED_AT,
        "is_default": row is None,
    }


async def get_admin_page(db: AsyncSession, slug: str) -> dict:
    row = await db.get(LegalPage, slug)
    return {
        "slug": slug,
        "title": TITLES[slug],
        "body": row.body if row else DEFAULTS[slug],
        "updated_at": row.updated_at if row else DEFAULTS_UPDATED_AT,
        "updated_by": row.updated_by if row else None,
        "is_default": row is None,
        "default_body": DEFAULTS[slug],
    }


async def save_page(db: AsyncSession, slug: str, body: str, admin_name: str | None) -> dict:
    body = body.replace("\r\n", "\n").strip() + "\n"
    row = await db.get(LegalPage, slug)
    if body.strip() == DEFAULTS[slug].strip():
        # Saving the default text unchanged = go back to following the default.
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(LegalPage(slug=slug, body=body, updated_by=admin_name))
    else:
        row.body = body
        row.updated_by = admin_name
    await db.commit()
    return await get_admin_page(db, slug)
