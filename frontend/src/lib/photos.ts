/**
 * Listing photos. The auction API has no images yet, so each seeded listing has a stock photo
 * and every other listing shows its category's. They are stock photos from Pexels (free to use
 * under the Pexels License), never pictures of the actual item, and the detail page says so.
 * Files live in public/images/auctions/; credits and sources below.
 */

export interface Photo {
  src: string;
  alt: string;
  photographer: string;
  source: string;
}

function pexels(file: string, id: number, slug: string, alt: string, photographer: string): Photo {
  return { src: `/images/auctions/${file}.jpg`, alt, photographer, source: `https://www.pexels.com/photo/${slug}-${id}/` };
}

/** The seeded catalogue (src/lib/mock/seed.ts and infra/postgres/seed/dev-seed.sql). */
const BY_AUCTION: Record<string, Photo> = {
  "00000000-0000-4000-8000-000000000201": pexels("vintage-film-camera", 8072960, "black-and-gray-old-canon-camera", "Vintage film cameras on a table", "Ahmet Bozkus"),
  "00000000-0000-4000-8000-000000000202": pexels("mechanical-keyboard", 12561283, "black-computer-keyboard-on-wooden-table", "Mechanical keyboard on a wooden desk", "An Tran"),
  "00000000-0000-4000-8000-000000000203": pexels("lounge-chair", 35589991, "elegant-minimalist-chair-in-modern-indoor-setting", "Wooden lounge chair with white cushions", "Pușcaș Adryan"),
  "00000000-0000-4000-8000-000000000204": pexels("dive-watch", 36426756, "close-up-of-seiko-diver-watch-on-strap", "Stainless steel dive watch", "Puneet Kaul"),
  "00000000-0000-4000-8000-000000000205": pexels("first-edition-novel", 17144197, "covers-of-vintage-books", "Old hardcover books on a shelf", "Merve Nur Türker"),
  "00000000-0000-4000-8000-000000000206": pexels("analog-synthesizer", 14251576, "close-up-of-an-analog-synthesizer", "Analog synthesizer knobs and patch cables", "TStudio"),
  "00000000-0000-4000-8000-000000000207": pexels("stoneware-tea-set", 5602530, "close-up-of-a-porcelain-tea-set-standing-on-a-wooden-tray", "Tea set with cups on a wooden tray", "cottonbro studio"),
};

const BY_CATEGORY: Record<string, Photo> = {
  cameras: pexels("cameras", 11333896, "black-and-silver-vintage-camera", "Vintage cameras in a display case", "Lokman Sevim"),
  electronics: pexels("electronics", 38094551, "colorful-mechanical-keyboard-on-wooden-desk", "Mechanical keyboard and mouse on a desk", "Pew Nguyen"),
  furniture: pexels("furniture", 35760083, "elegant-wooden-chair-in-cozy-interior-setting", "Wooden armchair in a warm interior", "betül nur akyürek"),
  watches: pexels("watches", 15649354, "hamilton-khaki-navy-scuba-auto-watch", "Wristwatch with an orange strap", "Osmany Mederos"),
  books: pexels("books", 19208445, "a-pile-of-old-books", "A pile of old books", "Beyzaa Yurtkuran"),
  music: pexels("music", 36064768, "analog-synthesizer-keyboard-close-up-with-dials", "Synthesizer keyboard with dials", "manu gvzman"),
  art: pexels("art", 7119222, "ceramic-vases-on-a-white-surface", "Two ceramic vases", "Ivan S"),
  jewelry: pexels("jewelry", 4735885, "a-floral-design-pendant-necklace-on-white-table", "Pendant necklaces on a white table", "Kaboompics.com"),
};

const FALLBACK = pexels("default", 15374671, "antiques-in-store", "Antiques on display in a shop", "Ayşenaz Bilgin");

export function photoFor(auctionId: string, category: string): Photo {
  return BY_AUCTION[auctionId] ?? BY_CATEGORY[category.trim().toLowerCase()] ?? FALLBACK;
}
