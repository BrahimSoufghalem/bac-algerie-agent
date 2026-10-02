/** Display-only adapter. Stored source JSON/Markdown are never rewritten.
 * CommonMark otherwise eats \( and \[, so adapt paired TeX delimiters
 * before parsing. Code spans/fences and ordinary/unpaired text stay literal.
 */
export function normalizeMathDelimiters(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const lineStart = i === 0 || text[i - 1] === "\n";
    const fence = lineStart
      ? /^ {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)/.exec(text.slice(i))
      : null;
    if (fence) {
      const marker = fence[1][0];
      const close = new RegExp(
        "^ {0,3}" + marker + "{" + fence[1].length + ",}[\\t ]*(?:\\n|$)",
        "gm",
      );
      close.lastIndex = i + fence[0].length;
      const match = close.exec(text);
      const end = match ? match.index + match[0].length : text.length;
      out += text.slice(i, end);
      i = end;
      continue;
    }
    const ticks = text[i] === "`" ? /^`+/.exec(text.slice(i))![0] : null;
    if (ticks) {
      const end = text.indexOf(ticks, i + ticks.length);
      if (end !== -1 && text[end - 1] !== "`" && text[end + ticks.length] !== "`") {
        out += text.slice(i, end + ticks.length);
        i = end + ticks.length;
        continue;
      }
    }
    if (text.startsWith("\\\\", i)) {
      out += "\\\\";
      i += 2;
      continue;
    }
    const inline = text.startsWith("\\(", i);
    const display = text.startsWith("\\[", i);
    if (inline || display) {
      const end = text.indexOf(inline ? "\\)" : "\\]", i + 2);
      if (end !== -1 && text.slice(i + 2, end).trim()) {
        const value = text.slice(i + 2, end);
        out += inline ? "$" + value + "$" : "\n$$\n" + value + "\n$$\n";
        i = end + 2;
        continue;
      }
    }
    out += text[i++];
  }
  return out;
}