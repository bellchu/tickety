# Tickety OPS Tower identity

Tickety OPS Tower uses the **Precision Window**: two balanced forms surrounding a
protected central case. The refined internal corners communicate rigor without
losing calmness. The relationship represents shared operational
visibility—customer and service team, intake and ownership, or two teams
working from the same accountable source of truth.

The identity is monochrome so it remains calm, authoritative, and dependable
across the product, customer portals, service documents, and small digital icons.

## Canonical construction

The mark is drawn on a `64 × 64` view box with two unmodified filled paths:

```text
Left   M12 8H26Q28 8 28 10V14Q28 16 26 16H18Q16 16 16 18V46Q16 48 18 48H26Q28 48 28 50V54Q28 56 26 56H12Q8 56 8 52V12Q8 8 12 8Z
Right  M52 8H38Q36 8 36 10V14Q36 16 38 16H46Q48 16 48 18V46Q48 48 46 48H38Q36 48 36 50V54Q36 56 38 56H52Q56 56 56 52V12Q56 8 52 8Z
```

The wordmark pairs the symbol with the full name `Tickety OPS Tower` in Geist Medium
500, falling back to Arial and then the system sans serif. Use approximately
`-0.025em` tracking and an 8 px gap beside a 32 px mark. The symbol is not a
letterform and never replaces the T in the written product name.

## Production assets

- `app/frontend-next/public/brand/tickety-mark.svg` — near-black mark
- `app/frontend-next/public/brand/tickety-mark-reversed.svg` — white mark
- `app/frontend-next/public/brand/tickety-lockup-primary.svg` — primary wordmark
- `app/frontend-next/public/brand/tickety-lockup-inverse.svg` — inverse wordmark
- `app/frontend-next/public/brand/tickety-social-card.svg` — social-card master
- `app/frontend-next/public/icons/icon-192.png` — standard install icon
- `app/frontend-next/public/icons/icon-512.png` — high-resolution install icon
- `app/frontend-next/public/icons/icon-maskable-512.png` — full-bleed maskable icon
- `app/frontend-next/app/icon.svg` — Next.js app icon
- `app/frontend-next/app/apple-icon.png` — 180 px Apple touch icon
- `app/frontend-next/app/favicon.ico` — 16, 32, and 48 px browser favicon
- `app/frontend-next/app/opengraph-image.png` — 1200 × 630 Open Graph image
- `app/frontend-next/app/twitter-image.png` — 1200 × 630 social preview image

## Color

| Token | Value | Use |
| --- | --- | --- |
| Identity ink | `#0A0B0D` | Primary mark, wordmark, and app-icon tile |
| Identity white | `#FFFFFF` | Reversed mark and app-icon artwork |
| UI cobalt | `#3D5AFE` | Product controls and interface emphasis only |

The logo never uses cobalt. It also never uses gradients, shadows, glows,
outlines, transparency effects, or multiple identity colors.

## Usage rules

- Keep clear space equal to at least one rail width on every side.
- Use primary artwork on light surfaces and inverse artwork on dark surfaces.
- Minimum bare digital mark size is `20 px`; minimum lockup height is `24 px`.
  The `16 px` favicon is a dedicated optical export and is not a general-use
  master.
- Scale both paths together. Preserve the central case and both eight-unit
  channels between the forms.
- Never merge the forms, change their balance, rotate, skew, stretch, crop,
  outline, decorate, or place content inside the central case.
- App icons use a near-black tile with the mark in white. Maskable artwork keeps
  the complete symbol inside the platform safe zone.
- Accessible product text and labels remain in the interface; logo artwork is
  never the sole label for an action.

Formal trademark clearance remains a separate legal and business gate.

Set `NEXT_PUBLIC_SITE_URL` to the deployed public origin so Open Graph and
Twitter image URLs resolve correctly outside local development.
