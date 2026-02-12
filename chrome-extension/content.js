chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "extractPageContent") {
    // Convert links to visible text so Claude can see URLs (especially LinkedIn, email mailto)
    const cloned = document.body.cloneNode(true);
    cloned.querySelectorAll("a[href]").forEach(a => {
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("javascript")) return;
      const linkText = a.textContent.trim();
      // Only annotate if the href adds info not already in the text
      if (href.includes("linkedin.com") || href.startsWith("mailto:")) {
        a.textContent = `${linkText} [${href}]`;
      }
    });

    const text = cloned.innerText;
    const url = window.location.href;
    const title = document.title;

    // Truncate text to ~15k chars to stay within Claude API limits
    const truncatedText = text.length > 15000 ? text.substring(0, 15000) + "\n[...truncated]" : text;

    sendResponse({ text: truncatedText, url, title });
  }
  return true;
});
