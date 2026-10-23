document.addEventListener("DOMContentLoaded", () => {
  const tickerInput = document.getElementById("ticker-search-input");
  const tickerDropdown = document.getElementById("ticker-dropdown-list");
  const quotePrice = document.getElementById("quote-price");
  const quoteChange1d = document.getElementById("quote-change-1d");
  const quoteChange30d = document.getElementById("quote-change-30d");
  const quoteRsi = document.getElementById("quote-rsi");
  const quoteTrend = document.getElementById("quote-trend");
  const newsFeed = document.getElementById("news-feed");
  const refreshNewsBtn = document.getElementById("refresh-news-btn");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const messagesContainer = document.getElementById("messages-container");
  const pills = document.querySelectorAll(".pill");

  let currentTicker = null;
  let currentResults = [];
  let activeIndex = -1;

  // Search autocomplete
  async function performSearch(query) {
    try {
      const res = await fetch(`/api/tickers/search?q=${encodeURIComponent(query)}&limit=15`);
      const data = await res.json();
      currentResults = data.results || [];
      renderDropdown(currentResults);
    } catch (err) {
      console.warn("Search failed:", err);
    }
  }

  function renderDropdown(items) {
    if (!items || items.length === 0) {
      tickerDropdown.innerHTML = `<div style="padding: 12px; color: var(--text-muted); font-size: 12px; text-align: center;">No matching companies found.</div>`;
      tickerDropdown.style.display = "block";
      return;
    }

    tickerDropdown.innerHTML = "";
    items.forEach((item, idx) => {
      const el = document.createElement("div");
      el.className = `combobox-item ${idx === activeIndex ? "active" : ""}`;
      el.innerHTML = `
        <div class="combobox-item-main">
          <span class="combobox-item-symbol">${item.nse_symbol}</span>
          <span class="combobox-item-name">${item.name}</span>
        </div>
        <span class="combobox-item-sector">${item.sector || "Equity"}</span>
      `;
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectCompany(item);
      });
      tickerDropdown.appendChild(el);
    });
    tickerDropdown.style.display = "block";
  }

  function selectCompany(item) {
    currentTicker = item.nse_symbol;
    tickerInput.value = `${item.nse_symbol} - ${item.name}`;
    tickerDropdown.style.display = "none";
    activeIndex = -1;
    onTickerChanged(currentTicker);
  }

  let searchTimeout = null;
  tickerInput.addEventListener("input", (e) => {
    const val = e.target.value.trim();
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      performSearch(val);
    }, 120);
  });

  tickerInput.addEventListener("focus", () => {
    // If the input already has a full selection, search for the symbol part
    const cleanSym = tickerInput.value.split(" - ")[0].trim();
    performSearch(cleanSym);
  });

  tickerInput.addEventListener("click", () => {
    if (tickerDropdown.style.display === "none" || !tickerDropdown.style.display) {
      const cleanSym = tickerInput.value.split(" - ")[0].trim();
      performSearch(cleanSym);
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-combobox")) {
      tickerDropdown.style.display = "none";
    }
  });

  tickerInput.addEventListener("keydown", (e) => {
    const items = tickerDropdown.querySelectorAll(".combobox-item");
    if (!items.length || tickerDropdown.style.display === "none") {
      if (e.key === "ArrowDown" || e.key === "Enter") {
        performSearch(tickerInput.value.split(" - ")[0].trim());
      }
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      updateActiveItem(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      updateActiveItem(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex >= 0 && activeIndex < currentResults.length) {
        selectCompany(currentResults[activeIndex]);
      }
    } else if (e.key === "Escape") {
      tickerDropdown.style.display = "none";
    }
  });

  function updateActiveItem(items) {
    items.forEach((it, idx) => {
      it.classList.toggle("active", idx === activeIndex);
      if (idx === activeIndex) {
        it.scrollIntoView({ block: "nearest" });
      }
    });
  }

  // Load company overview (quote + indicators)
  async function loadOverview(sym) {
    quotePrice.textContent = "...";
    quoteChange1d.textContent = "...";
    quoteChange30d.textContent = "...";
    quoteRsi.textContent = "...";
    quoteTrend.textContent = "...";

    try {
      const res = await fetch(`/api/tickers/${sym}/overview`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      
      const p = data.price_summary;
      const ind = data.indicators;

      if (p && !p.error && p.last_close !== null && p.last_close !== undefined) {
        quotePrice.textContent = `₹${Number(p.last_close).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        
        const chg1d = (p.change_1d_pct !== undefined && p.change_1d_pct !== null) ? Number(p.change_1d_pct).toFixed(2) : "0.00";
        quoteChange1d.textContent = `${Number(chg1d) >= 0 ? "+" : ""}${chg1d}%`;
        quoteChange1d.className = `val ${Number(chg1d) >= 0 ? "up" : "down"}`;

        const raw30d = (p.return_30d_pct !== undefined && p.return_30d_pct !== null) ? p.return_30d_pct : (p.change_pct || 0.0);
        const chg30d = Number(raw30d).toFixed(2);
        quoteChange30d.textContent = `${Number(chg30d) >= 0 ? "+" : ""}${chg30d}%`;
        quoteChange30d.className = `val ${Number(chg30d) >= 0 ? "up" : "down"}`;
        if (p.period_start && p.as_of) {
          quoteChange30d.title = `30 calendar days (${p.period_start} to ${p.as_of})`;
        }
      } else {
        quotePrice.textContent = "--";
        quoteChange1d.textContent = "--";
        quoteChange30d.textContent = "--";
      }

      if (ind && !ind.error && ind.rsi_14 !== null && ind.rsi_14 !== undefined) {
        const rsiVal = ind.rsi_14;
        let rsiTag = "";
        if (typeof rsiVal === "number") {
          if (rsiVal >= 70) rsiTag = " (Overbought)";
          else if (rsiVal <= 30) rsiTag = " (Oversold)";
        }
        quoteRsi.textContent = `${rsiVal}${rsiTag}`;
        
        let trend = "Neutral";
        if (ind.price_vs_sma50_pct !== null && ind.price_vs_sma50_pct !== undefined) {
          if (ind.price_vs_sma50_pct > 0 && (ind.price_vs_sma200_pct === null || ind.price_vs_sma200_pct > 0)) {
            trend = "Bullish (>50 SMA)";
          } else if (ind.price_vs_sma50_pct < 0 && (ind.price_vs_sma200_pct === null || ind.price_vs_sma200_pct < 0)) {
            trend = "Bearish (<50 SMA)";
          } else {
            trend = "Consolidating";
          }
        }
        quoteTrend.textContent = trend;
      } else {
        quoteRsi.textContent = "--";
        quoteTrend.textContent = "--";
      }

      // Concall status tag
      const concallTag = document.getElementById("concall-status-tag");
      if (concallTag) {
        const filings = data.filings;
        if (filings && filings.indexed) {
          concallTag.style.display = "inline-flex";
          concallTag.className = "concall-status-tag active";
          concallTag.innerHTML = `Concall: ${filings.fiscal_year} ${filings.quarter}`;
          concallTag.title = `${filings.latest_title || 'Latest transcript'}\nLast Synced: ${filings.last_synced || ''}`;
        } else {
          concallTag.style.display = "inline-flex";
          concallTag.className = "concall-status-tag";
          concallTag.innerHTML = `Concall: Syncing latest...`;
          setTimeout(async () => {
            try {
              const fRes = await fetch(`/api/filings/${sym}/status`);
              if (fRes.ok) {
                const fData = await fRes.json();
                if (fData.indexed) {
                  concallTag.className = "concall-status-tag active";
                  concallTag.innerHTML = `Concall: ${fData.fiscal_year} ${fData.quarter}`;
                  concallTag.title = `${fData.latest_title || 'Latest transcript'}\nLast Synced: ${fData.last_synced || ''}`;
                }
              }
            } catch (_) {}
          }, 3500);
        }
      }
    } catch (e) {
      console.warn("Could not load overview:", e);
      quotePrice.textContent = "--";
      const concallTag = document.getElementById("concall-status-tag");
      if (concallTag) concallTag.style.display = "none";
      quoteChange1d.textContent = "--";
      quoteChange30d.textContent = "--";
      quoteRsi.textContent = "--";
      quoteTrend.textContent = "--";
    }
  }

  // Load clustered news
  async function loadNews(sym, refresh = false) {
    newsFeed.innerHTML = `<div class="loading-placeholder">Fetching top 10 events for ${sym}...</div>`;
    try {
      const res = await fetch(`/api/news/clusters/${sym}?refresh=${refresh}`);
      const data = await res.json();
      
      if (!data.clusters || data.clusters.length === 0) {
        newsFeed.innerHTML = `<div class="loading-placeholder">No major corporate events recorded in the last 3 days for ${sym}.</div>`;
        return;
      }

      // Sort strictly from most recent to oldest
      const sortedClusters = (data.clusters || []).slice().sort((a, b) => {
        const timeA = a.published_ts ? a.published_ts : (a.date ? Date.parse(a.date) || 0 : 0);
        const timeB = b.published_ts ? b.published_ts : (b.date ? Date.parse(b.date) || 0 : 0);
        return timeB - timeA;
      });

      newsFeed.innerHTML = "";
      sortedClusters.slice(0, 10).forEach(c => {
        const card = document.createElement("div");
        card.className = "news-card";
        
        // Render outlet pills for all reporting newspapers
        const outletPills = (c.outlets || []).map(outlet => 
          `<span class="outlet-pill">${escapeHtml(outlet)}</span>`
        ).join(" ");

        // Direct article link button
        const primaryUrl = (c.sources && c.sources.length > 0) ? c.sources[0].url : "";
        const readBtn = primaryUrl ? `<a href="${primaryUrl}" target="_blank" rel="noopener" class="news-link-btn">Read ↗</a>` : "";

        card.innerHTML = `
          <div class="news-card-title">${escapeHtml(c.theme_title)}</div>
          <div class="news-card-summary">${escapeHtml(c.summary)}</div>
          <div class="news-card-footer">
            <div class="outlet-tags">${outletPills}</div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="news-card-date">${escapeHtml(c.date || "Recent")}</span>
              ${readBtn}
            </div>
          </div>
        `;
        newsFeed.appendChild(card);
      });
    } catch (e) {
      newsFeed.innerHTML = `<div class="loading-placeholder">Failed to load news clusters.</div>`;
    }
  }

  function onTickerChanged(sym) {
    currentTicker = sym;
    loadOverview(sym);
    loadNews(sym, false);
  }

  refreshNewsBtn.addEventListener("click", () => {
    if (currentTicker) {
      loadNews(currentTicker, true);
    } else {
      newsFeed.innerHTML = `<div class="loading-placeholder">Select a stock from the top bar to view top 10 market events and news clusters.</div>`;
      tickerInput.focus();
    }
  });

  // Quick Prompt Pills
  pills.forEach(pill => {
    pill.addEventListener("click", () => {
      const promptText = pill.getAttribute("data-prompt");
      if (currentTicker) {
        chatInput.value = promptText;
        chatForm.dispatchEvent(new Event("submit"));
      } else {
        chatInput.value = promptText;
        tickerInput.focus();
      }
    });
  });

  // Chat Submission
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    chatInput.value = "";
    appendMessage("user", query);

    const loadingId = appendLoading();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: query, ticker: currentTicker })
      });

      const data = await res.json();
      removeLoading(loadingId);
      appendMessage("assistant", data.answer, data.sources, data.tool_log);
    } catch (err) {
      removeLoading(loadingId);
      appendMessage("assistant", `Connection error: ${err.message}. Please verify the backend is running.`);
    }
  });

  function appendMessage(role, text, sources = [], toolLog = []) {
    const msg = document.createElement("div");
    msg.className = `message ${role}`;

    let bodyHtml = renderMarkdown(text);

    // Citations Drawer (Verified sources only, no internal tool calls)
    if (sources && sources.length > 0) {
      const citationItems = sources.map(s => `
        <div class="citation-row">
          <span class="citation-tag">${s.type || "Source"}</span>
          <span>${escapeHtml(s.source || s.url || s.symbol || "Filing")} ${s.page ? `(Page ${s.page})` : ""} ${s.fiscal_year ? `• ${s.fiscal_year}` : ""}</span>
        </div>
      `).join("");

      bodyHtml += `
        <details class="evidence-drawer">
          <summary class="evidence-header">Verified Sources (${sources.length})</summary>
          <div class="evidence-content">
            ${citationItems}
          </div>
        </details>
      `;
    }

    msg.innerHTML = `
      <div class="msg-body">${bodyHtml}</div>
    `;

    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function appendLoading() {
    const id = "loading-" + Date.now();
    const msg = document.createElement("div");
    msg.id = id;
    msg.className = "message assistant";
    msg.innerHTML = `
      <div class="msg-body" style="color: var(--text-muted); font-style: italic;">
        Consulting real price data, filings RAG, and news clusters...
      </div>
    `;
    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return id;
  }

  function removeLoading(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderMarkdown(md) {
    if (!md) return "";
    let html = escapeHtml(md);

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    
    // Inline code
    html = html.replace(/`([^`]+)`/g, "<code style='background: rgba(255,255,255,0.08); padding: 1px 4px; border-radius: 3px; font-family: monospace;'>$1</code>");

    // Markdown Table Parser
    const lines = html.split("\n");
    const outputBlocks = [];
    let inTable = false;
    let tableRows = [];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith("|") && line.endsWith("|")) {
        // Table line
        if (line.match(/^\|[\s\-:|]+\|$/)) {
          // Separator row, ignore
          continue;
        }
        const cells = line.slice(1, -1).split("|").map(c => c.trim());
        tableRows.push(cells);
        inTable = true;
      } else {
        if (inTable && tableRows.length > 0) {
          // Render table
          let tableHtml = "<div style='overflow-x: auto; margin: 12px 0;'><table style='width: 100%; border-collapse: collapse; font-size: 12px;'>";
          tableRows.forEach((row, rIdx) => {
            const tag = rIdx === 0 ? "th" : "td";
            tableHtml += `<tr>${row.map(cell => `<${tag} style='border: 1px solid #27272a; padding: 6px 10px; text-align: left; ${rIdx === 0 ? "background: #181818; color: #fff; font-weight: 600;" : ""}'>${cell}</${tag}>`).join("")}</tr>`;
          });
          tableHtml += "</table></div>";
          outputBlocks.push(tableHtml);
          tableRows = [];
          inTable = false;
        }

        if (line.startsWith("### ")) {
          outputBlocks.push(`<h3 style="font-size: 13.5px; font-weight: 600; margin: 12px 0 6px 0; color: #ffffff;">${line.slice(4)}</h3>`);
        } else if (line.startsWith("## ")) {
          outputBlocks.push(`<h2 style="font-size: 14.5px; font-weight: 600; margin: 14px 0 6px 0; color: #ffffff;">${line.slice(3)}</h2>`);
        } else if (line.startsWith("- ") || line.startsWith("* ")) {
          outputBlocks.push(`<ul><li>${line.slice(2)}</li></ul>`);
        } else if (line.length > 0) {
          outputBlocks.push(`<p>${line}</p>`);
        }
      }
    }

    if (inTable && tableRows.length > 0) {
      let tableHtml = "<div style='overflow-x: auto; margin: 12px 0;'><table style='width: 100%; border-collapse: collapse; font-size: 12px;'>";
      tableRows.forEach((row, rIdx) => {
        const tag = rIdx === 0 ? "th" : "td";
        tableHtml += `<tr>${row.map(cell => `<${tag} style='border: 1px solid #27272a; padding: 6px 10px; text-align: left; ${rIdx === 0 ? "background: #181818; color: #fff; font-weight: 600;" : ""}'>${cell}</${tag}>`).join("")}</tr>`;
      });
      tableHtml += "</table></div>";
      outputBlocks.push(tableHtml);
    }

    return outputBlocks.join("");
  }

  // Front starts empty until user chooses a stock
});
