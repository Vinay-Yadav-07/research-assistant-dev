/** Character ranges `[start, end)` to highlight, per pdf.js text item index. */
export type Highlights = Map<number, [number, number][]>;

type Item = { str?: string; hasEOL?: boolean };

// A word may continue over a line-end hyphen ("signifi-" / "cantly").
const WORD = /[\p{L}\p{N}]+(?:-\n[\p{L}\p{N}]+)*/gu;

function words(text: string) {
  return Array.from(text.matchAll(WORD), (m) => ({
    word: m[0].replace(/-\n/g, "").toLowerCase(),
    start: m.index,
    end: m.index + m[0].length,
  }));
}

/**
 * Finds the quote on a PDF page and returns the text ranges to mark. Matches on lowercase words
 * of the whole page, so words split over several text items, line-end hyphens, markdown or HTML
 * tags, punctuation and a cut-off "…" in the stored quote do not matter. Takes the longest run of
 * quote words found on the page, so a quote that crosses a page break still marks its part on
 * each page. Returns an empty map when no run of `minRun` words matches.
 */
export function findQuote(
  items: ReadonlyArray<Item>,
  quote: string,
  minRun = 5,
): Highlights {
  const q = words(quote.replace(/<[^>]*>/g, " ")).map((w) => w.word);
  // The page text, with each character's text item and offset in it (-1 for line breaks).
  let text = "";
  const owner: [number, number][] = [];
  items.forEach((item, i) => {
    const str = item.str ?? "";
    for (let k = 0; k < str.length; k++) owner.push([i, k]);
    text += str;
    if (item.hasEOL) {
      owner.push([-1, -1]);
      text += "\n";
    }
  });
  const page = words(text);

  // Longest common run of words (dynamic programming over one rolling row).
  let best = 0;
  let bestEnd = 0;
  let prev = new Array<number>(q.length + 1).fill(0);
  for (let i = 1; i <= page.length; i++) {
    const row = new Array<number>(q.length + 1).fill(0);
    for (let j = 1; j <= q.length; j++) {
      if (page[i - 1].word === q[j - 1]) {
        row[j] = prev[j - 1] + 1;
        if (row[j] > best) [best, bestEnd] = [row[j], i];
      }
    }
    prev = row;
  }

  const highlights: Highlights = new Map();
  if (best === 0 || best < Math.min(minRun, q.length)) return highlights;
  const from = page[bestEnd - best].start;
  const to = page[bestEnd - 1].end;
  for (const [item, offset] of owner.slice(from, to)) {
    if (item === -1) continue;
    const ranges = highlights.get(item);
    // Characters of one item in the run are contiguous, so one range per item spans them.
    if (ranges) ranges[0][1] = offset + 1;
    else highlights.set(item, [[offset, offset + 1]]);
  }
  return highlights;
}

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escape(text: string) {
  return text.replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

/** The HTML for one text-layer item with its highlighted ranges wrapped in `<mark>`. */
export function markItem(str: string, ranges: [number, number][] = []) {
  let html = "";
  let cursor = 0;
  for (const [start, end] of ranges) {
    html += `${escape(str.slice(cursor, start))}<mark>${escape(str.slice(start, end))}</mark>`;
    cursor = end;
  }
  return html + escape(str.slice(cursor));
}
