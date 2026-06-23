"use strict";

/*
 * Render -- a small REUSABLE module for turning model/text output into rich,
 * safe HTML. Any page can drop in marked + DOMPurify + KaTeX + highlight.js
 * (see the <head> includes) and this file, then call:
 *
 *     Render.rich(element, text);   // markdown + math + code + copy buttons
 *     Render.markdown(text);        // -> sanitized HTML string
 *
 * Keeping it separate means the chat page, the memory page, and any future
 * screen all format text exactly the same way.
 */
window.Render = (function () {
  function markdown(text) {
    return DOMPurify.sanitize(marked.parse(text || ""));
  }

  function addCodeCopyButtons(root) {
    root.querySelectorAll("pre").forEach((pre) => {
      if (pre.parentElement && pre.parentElement.classList.contains("codeblock")) return;
      const wrap = document.createElement("div");
      wrap.className = "codeblock";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "code-copy";
      btn.textContent = "Copy";
      btn.addEventListener("click", () => {
        navigator.clipboard.writeText(pre.innerText);
        btn.textContent = "Copied";
        setTimeout(() => (btn.textContent = "Copy"), 1200);
      });
      wrap.appendChild(btn);
    });
  }

  function rich(element, text) {
    element.dataset.raw = text;

    // Markdown would mangle LaTeX delimiters (\( -> (, etc.), so pull math out
    // first, run markdown, then restore it untouched for KaTeX.
    const math = [];
    const stash = (m) => { math.push(m); return `@@MATH${math.length - 1}@@`; };
    let prepared = (text || "")
      .replace(/\\\[[\s\S]*?\\\]/g, stash)
      .replace(/\$\$[\s\S]*?\$\$/g, stash)
      .replace(/\\\([\s\S]*?\\\)/g, stash);

    let html = markdown(prepared);
    html = html.replace(/@@MATH(\d+)@@/g, (_, i) => math[i]);
    element.innerHTML = html;

    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(element, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "\\[", right: "\\]", display: true },
            { left: "\\(", right: "\\)", display: false },
          ],
          throwOnError: false,
        });
      } catch (e) { /* leave raw math if KaTeX trips */ }
    }
    if (window.hljs) {
      element.querySelectorAll("pre code").forEach((el) => window.hljs.highlightElement(el));
    }
    addCodeCopyButtons(element);
  }

  return { markdown, rich };
})();
