/* =============================================================
   AGENT-VIEW — view.js
   Dependency-free vanilla JS panel renderer.
   Attaches to window.RV.renderApp(mountEl, state, meta).
   No import/export. No build tooling. Concatenated by BUILD.
   ============================================================= */

(function (global) {
  'use strict';

  global.RV = global.RV || {};

  /* ----------------------------------------------------------
     Tiny helpers
  ---------------------------------------------------------- */

  /** Safely set textContent on a freshly-created element. */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  /** Format a USD dollar amount to 2-4 significant decimals. */
  function usd(n) {
    if (n === null || n === undefined) return '$0.00';
    var num = Number(n);
    if (num === 0) return '$0.00';
    if (num < 0.01) return '$' + num.toFixed(4);
    return '$' + num.toFixed(2);
  }

  /** Render stars for a reputation value 0..1 (5 stars). */
  function starsHTML(reputation) {
    var total = 5;
    var filled = Math.round(reputation * total);
    var out = '';
    for (var i = 0; i < total; i++) {
      if (i < filled) {
        out += '<span class="rv-star rv-star--full" aria-hidden="true">★</span>';
      } else {
        out += '<span class="rv-star rv-star--empty" aria-hidden="true">★</span>';
      }
    }
    return out;
  }

  /** Truncate a hex string to first8…last6. Safe for null/undefined. */
  function truncateHex(s) {
    if (!s) return '';
    var str = String(s);
    if (str.length <= 18) return str;
    return str.slice(0, 10) + '…' + str.slice(-6);
  }

  /**
   * Pretty-print a worker id: "liability" -> "Liability", "tax-bot" -> "Tax Bot".
   * Avoids XSS — used only for display labels, always set via textContent.
   */
  function prettyWorker(w) {
    if (!w) return '';
    return String(w)
      .replace(/[-_]/g, ' ')
      .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  /**
   * Render room message content: highlight @mentions.
   * Returns an array of DOM nodes (span). Uses textContent only — no innerHTML
   * on user-provided content.
   */
  function renderRoomContent(content) {
    var parts = String(content || '').split(/(@[\w-]+)/g);
    var nodes = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p.charAt(0) === '@') {
        var s = el('span', 'rv-room-mention');
        s.textContent = p;
        nodes.push(s);
      } else {
        nodes.push(document.createTextNode(p));
      }
    }
    return nodes;
  }

  /** Deterministic pastel-on-dark background color for avatars from a seed string. */
  function avatarColor(seed) {
    var palette = [
      '#1a7a4a', '#7a3d1a', '#1a4a7a', '#5a1a7a',
      '#7a1a4a', '#1a6a7a', '#7a6a1a', '#3a1a7a',
    ];
    var h = 0;
    for (var i = 0; i < seed.length; i++) {
      h = (h * 31 + seed.charCodeAt(i)) | 0;
    }
    return palette[Math.abs(h) % palette.length];
  }

  /** Initials from a name or worker id. */
  function initials(name) {
    var parts = String(name || '').replace(/[-_]/g, ' ').trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return (parts[0] || '?').slice(0, 2).toUpperCase();
  }

  /** Build a small avatar div using CSS background color + initials. */
  function makeAvatar(seed, size) {
    var d = el('div', 'rv-room-avatar');
    d.style.background = avatarColor(seed);
    d.style.width = (size || 28) + 'px';
    d.style.height = (size || 28) + 'px';
    d.style.fontSize = Math.floor((size || 28) * 0.38) + 'px';
    d.textContent = initials(seed);
    d.setAttribute('aria-hidden', 'true');
    return d;
  }

  /** Render an inline progress bar as an HTMLElement. */
  function makeBar(value, tone) {
    var wrap = el('div', 'rv-bar-track');
    var fill = el('div', 'rv-bar-fill rv-bar-fill--' + (tone || 'emerald'));
    fill.style.width = Math.round(Math.min(1, Math.max(0, value || 0)) * 100) + '%';
    wrap.appendChild(fill);
    return wrap;
  }

  /* ----------------------------------------------------------
     ① HEADER
  ---------------------------------------------------------- */

  function renderHeader(meta) {
    var section = el('div', 'rv-header');
    var inner = el('div', 'rv-header-inner');

    // Left: icon + title
    var logo = el('div', 'rv-header-logo');
    var icon = el('div', 'rv-header-icon');
    icon.textContent = '⇄';
    logo.appendChild(icon);

    var textBlock = el('div');
    var eyebrow = el('div', 'rv-eyebrow');
    eyebrow.textContent = 'AGENT EXCHANGE · REPLAY';

    var title = el('div', 'rv-header-title');
    title.textContent = meta.title || 'Replay';

    var subtitle = el('div', 'rv-header-subtitle');
    subtitle.textContent = 'Job: ' + (meta.job_id || '—') + ' · Recorded ' + (meta.recorded_at ? meta.recorded_at.slice(0, 10) : '—');

    textBlock.appendChild(eyebrow);
    textBlock.appendChild(title);
    textBlock.appendChild(subtitle);
    logo.appendChild(textBlock);
    inner.appendChild(logo);

    // Right: mode badge + kind badge + budget
    var metaBlock = el('div', 'rv-header-meta');

    var modeClass = (meta.mode === 'live') ? 'rv-badge rv-badge--live' : 'rv-badge rv-badge--sim';
    var modeBadge = el('span', modeClass);
    modeBadge.textContent = (meta.mode || 'sim').toUpperCase();

    var kindBadge = el('span', 'rv-badge rv-badge--kind');
    kindBadge.textContent = (meta.kind || '').replace(/-/g, ' ').toUpperCase();

    var budget = el('div', 'rv-header-budget');
    budget.textContent = 'Budget: ' + usd(meta.budget_usd);

    metaBlock.appendChild(modeBadge);
    metaBlock.appendChild(kindBadge);
    metaBlock.appendChild(budget);
    inner.appendChild(metaBlock);

    section.appendChild(inner);
    return section;
  }

  /* ----------------------------------------------------------
     ② STAGE BAR
  ---------------------------------------------------------- */

  function renderStageBar(stages) {
    var panel = el('div', 'rv-panel rv-stagebar');

    var header = el('div', 'rv-panel-header');
    var eyebrow = el('div', 'rv-eyebrow');
    eyebrow.textContent = 'LIFECYCLE · STAGES';
    var title = el('div', 'rv-panel-title');
    title.textContent = '⬤  PIPELINE';
    header.appendChild(eyebrow);
    header.appendChild(title);
    panel.appendChild(header);

    var inner = el('div', 'rv-stagebar-inner');

    (stages || []).forEach(function (s, i) {
      var status = s.status || 'pending';
      var item = el('div', 'rv-stage-item');

      // Node
      var node = el('div', 'rv-stage-node rv-stage-node--' + status);

      // Icon
      var icon = el('span', 'rv-stage-icon');
      if (status === 'done') {
        icon.textContent = '✓';
        icon.style.color = '#2bff9a';
        icon.style.fontWeight = '900';
      } else if (status === 'error') {
        icon.textContent = '✗';
        icon.style.color = '#ff3b5c';
        icon.style.fontWeight = '900';
      } else if (status === 'active') {
        var dot = el('span', 'rv-stage-dot rv-stage-dot--active');
        icon.appendChild(dot);
      } else {
        var dotP = el('span', 'rv-stage-dot rv-stage-dot--pending');
        icon.appendChild(dotP);
      }
      node.appendChild(icon);

      // Label
      var label = el('span', 'rv-stage-label rv-stage-label--' + status);
      label.textContent = s.name;
      node.appendChild(label);

      item.appendChild(node);

      // Connector (not after last)
      if (i < stages.length - 1) {
        var conn = el('div', 'rv-stage-connector');
        var fill = el('div', 'rv-stage-connector-fill');
        fill.style.width = (status === 'done') ? '100%' : '0%';
        conn.appendChild(fill);
        item.appendChild(conn);
      }

      inner.appendChild(item);
    });

    panel.appendChild(inner);
    return panel;
  }

  /* ----------------------------------------------------------
     ③ BID FEED
  ---------------------------------------------------------- */

  function renderBidFeed(pool, bids, hire, hiredWorkers) {
    var panel = el('div', 'rv-panel');

    // Header
    var header = el('div', 'rv-panel-header');
    var leftCol = el('div');
    var eyebrow = el('div', 'rv-eyebrow rv-eyebrow--emerald');
    eyebrow.textContent = 'MARKETPLACE · OPEN BIDS';
    var title = el('div', 'rv-panel-title');
    title.textContent = '🤖  MARKET';
    leftCol.appendChild(eyebrow);
    leftCol.appendChild(title);
    header.appendChild(leftCol);

    // Right: hired count + bid count
    var rightCol = el('div', 'rv-settle-totals');
    if (hiredWorkers && hiredWorkers.size > 0) {
      var hiredCount = 0;
      (bids || []).forEach(function (b) { if (hiredWorkers.has(b.worker)) hiredCount++; });
      if (hiredCount > 0) {
        var hchip = el('span', 'rv-tally-chip rv-tally-chip--confirmed');
        hchip.textContent = '✓ ' + hiredCount + ' hired';
        rightCol.appendChild(hchip);
      }
    }
    var countSpan = el('span', 'rv-eyebrow');
    countSpan.textContent = (bids ? bids.length : 0) + ' bids · ' + (pool ? pool.length : 0) + ' pool';
    rightCol.appendChild(countSpan);
    header.appendChild(rightCol);
    panel.appendChild(header);

    // Cards grid
    if (!bids || bids.length === 0) {
      var emp = el('div', 'rv-empty');
      emp.textContent = 'Agents appear here as the pool is discovered.';
      panel.appendChild(emp);
    } else {
      var declined = new Set((hire && hire.declined) ? hire.declined : []);
      var grid = el('div', 'rv-bidfeed-grid');

      bids.forEach(function (bid) {
        var isHired = hiredWorkers && hiredWorkers.has(bid.worker);
        var isDeclined = declined.has(bid.worker);

        // Find matching pool agent
        var poolAgent = null;
        var wNorm = String(bid.worker || '').toLowerCase().replace(/[^a-z]/g, '');
        if (pool) {
          for (var pi = 0; pi < pool.length; pi++) {
            var p = pool[pi];
            var hay = (p.id + ' ' + p.handle + ' ' + p.name).toLowerCase().replace(/[^a-z]/g, '');
            if (hay.indexOf(wNorm) !== -1 || wNorm.indexOf(p.id.toLowerCase().replace(/[^a-z]/g, '')) !== -1) {
              poolAgent = p;
              break;
            }
          }
        }

        var cardCls = 'rv-bid-card';
        if (isHired) cardCls += ' rv-bid-card--hired';
        else if (isDeclined) cardCls += ' rv-bid-card--declined';
        var card = el('article', cardCls);

        // Card header row
        var cardHead = el('div', 'rv-bid-card-header');

        var workerInfo = el('div');
        var nameEl = el('div', 'rv-bid-worker-name');
        nameEl.textContent = (poolAgent && poolAgent.name) ? poolAgent.name : prettyWorker(bid.worker);
        workerInfo.appendChild(nameEl);

        var handleEl = el('div', 'rv-bid-worker-handle');
        handleEl.textContent = '@' + (bid.worker || '');
        workerInfo.appendChild(handleEl);

        if (isHired) {
          var hBadge = el('div', 'rv-badge--hired');
          hBadge.textContent = '✓ Hired';
          workerInfo.appendChild(hBadge);
        } else if (isDeclined) {
          var dBadge = el('div', 'rv-badge--declined');
          dBadge.textContent = 'Passed';
          workerInfo.appendChild(dBadge);
        }

        cardHead.appendChild(workerInfo);

        var priceEl = el('div', 'rv-bid-price');
        priceEl.textContent = usd(bid.price_usd);
        cardHead.appendChild(priceEl);
        card.appendChild(cardHead);

        // Cross-owner badge
        if (poolAgent && poolAgent.cross_owner) {
          var coBadge = el('div', 'rv-badge--cross-owner');
          coBadge.textContent = '⇄ cross-owner agent';
          card.appendChild(coBadge);
        }

        // Stars
        var starsWrap = el('div', 'rv-stars');
        starsWrap.innerHTML = starsHTML(bid.reputation);
        card.appendChild(starsWrap);

        // Relevance bar
        var relRow = el('div', 'rv-bar-row');
        var relLabel = el('div', 'rv-bar-label-row');
        var relL = el('span');
        relL.textContent = 'relevance';
        var relV = el('span');
        relV.textContent = Math.round((bid.relevance || 0) * 100) + '%';
        relLabel.appendChild(relL);
        relLabel.appendChild(relV);
        relRow.appendChild(relLabel);
        relRow.appendChild(makeBar(bid.relevance, 'emerald'));
        card.appendChild(relRow);

        grid.appendChild(card);
      });

      panel.appendChild(grid);
    }

    // Hire policy footer
    if (hire) {
      var footer = el('div', 'rv-hire-policy');
      var pLabel = el('div', 'rv-hire-policy-label');
      pLabel.textContent = 'Hiring policy';
      footer.appendChild(pLabel);
      var pText = el('p');
      pText.textContent = hire.strategy + ' (target pay fraction ' + Math.round((hire.pay_fraction_target || 0) * 100) + '%)';
      footer.appendChild(pText);
      panel.appendChild(footer);
    }

    return panel;
  }

  /* ----------------------------------------------------------
     ④ WORK ROOM
  ---------------------------------------------------------- */

  function renderWorkRoom(room) {
    var panel = el('div', 'rv-panel');

    var header = el('div', 'rv-panel-header');
    var leftCol = el('div');
    var eyebrow = el('div', 'rv-eyebrow');
    eyebrow.textContent = 'COLLAB · SHARED TRANSCRIPT';
    var title = el('div', 'rv-panel-title');
    title.textContent = '🤖  WORK ROOM';
    leftCol.appendChild(eyebrow);
    leftCol.appendChild(title);
    header.appendChild(leftCol);

    var countSpan = el('span', 'rv-eyebrow');
    countSpan.textContent = (room ? room.length : 0) + ' msg' + ((room && room.length === 1) ? '' : 's');
    header.appendChild(countSpan);
    panel.appendChild(header);

    var messages = el('div', 'rv-workroom-messages');

    if (!room || room.length === 0) {
      var emp = el('div', 'rv-empty');
      emp.textContent = 'The transcript streams here once the team starts working.';
      messages.appendChild(emp);
    } else {
      room.forEach(function (line) {
        var isSystem = (line.sender || '').toLowerCase().indexOf('reporter') !== -1 ||
                       (line.sender || '').toLowerCase().indexOf('coordinator') !== -1;

        var lineEl = el('div', 'rv-room-line');
        lineEl.appendChild(makeAvatar(line.sender, 28));

        var content = el('div', 'rv-room-content');

        var senderRow = el('div', 'rv-room-sender-row');
        var senderName = el('span', 'rv-room-sender');
        senderName.textContent = line.sender;
        senderRow.appendChild(senderName);
        if (isSystem) {
          var sysBadge = el('span', 'rv-room-system-badge');
          sysBadge.textContent = 'system';
          senderRow.appendChild(sysBadge);
        }
        content.appendChild(senderRow);

        var bubbleCls = 'rv-room-bubble' + (isSystem ? ' rv-room-bubble--system' : '');
        var bubble = el('div', bubbleCls);
        // Safely render content with @mention highlighting
        var nodes = renderRoomContent(line.content);
        for (var ni = 0; ni < nodes.length; ni++) {
          bubble.appendChild(nodes[ni]);
        }
        content.appendChild(bubble);
        lineEl.appendChild(content);
        messages.appendChild(lineEl);
      });
    }

    panel.appendChild(messages);
    return panel;
  }

  /* ----------------------------------------------------------
     ⑤ FINDINGS / VERIFY
  ---------------------------------------------------------- */

  function verdictInfo(verdict) {
    switch (verdict) {
      case 'confirmed':
        return { glyph: '✓', label: 'Confirmed', cls: 'confirmed', barTone: 'emerald' };
      case 'partial':
        return { glyph: '~', label: 'Partial', cls: 'partial', barTone: 'gold' };
      case 'unsupported':
        return { glyph: '✗', label: 'Unsupported', cls: 'unsupported', barTone: 'red' };
      default:
        return { glyph: '?', label: verdict || 'Unknown', cls: 'confirmed', barTone: 'emerald' };
    }
  }

  function renderFindings(findings) {
    var panel = el('div', 'rv-panel');

    var header = el('div', 'rv-panel-header');
    var leftCol = el('div');
    var eyebrow = el('div', 'rv-eyebrow rv-eyebrow--emerald');
    eyebrow.textContent = 'VERIFIER · CLAIM vs DOCUMENT';
    var title = el('div', 'rv-panel-title');
    title.textContent = '⚖  VERIFICATION';
    leftCol.appendChild(eyebrow);
    leftCol.appendChild(title);
    header.appendChild(leftCol);

    // Tally chips
    if (findings && findings.length > 0) {
      var tally = el('div', 'rv-verdict-tally');
      var confirmed = 0, partial = 0, unsupported = 0;
      findings.forEach(function (f) {
        if (f.verdict === 'confirmed') confirmed++;
        else if (f.verdict === 'partial') partial++;
        else if (f.verdict === 'unsupported') unsupported++;
      });
      if (confirmed > 0) {
        var c = el('span', 'rv-tally-chip rv-tally-chip--confirmed');
        c.textContent = '✓ ' + confirmed;
        tally.appendChild(c);
      }
      if (partial > 0) {
        var pp = el('span', 'rv-tally-chip rv-tally-chip--partial');
        pp.textContent = '~ ' + partial;
        tally.appendChild(pp);
      }
      if (unsupported > 0) {
        var u = el('span', 'rv-tally-chip rv-tally-chip--unsupported');
        u.textContent = '✗ ' + unsupported;
        tally.appendChild(u);
      }
      header.appendChild(tally);
    }

    panel.appendChild(header);

    if (!findings || findings.length === 0) {
      var emp = el('div', 'rv-empty');
      emp.textContent = 'Graded findings appear here as the verifier checks each claim against the text.';
      panel.appendChild(emp);
      return panel;
    }

    var list = el('div', 'rv-findings-list');

    findings.forEach(function (f) {
      var info = verdictInfo(f.verdict);
      var isFake = f.verdict === 'unsupported';

      var card = el('li', 'rv-finding-card rv-finding-card--' + info.cls);
      var row = el('div', 'rv-finding-row');

      // Verdict tile
      var tile = el('span', 'rv-verdict-tile rv-verdict-tile--' + info.cls);
      tile.textContent = info.glyph;
      tile.setAttribute('aria-label', info.label);
      row.appendChild(tile);

      var body = el('div', 'rv-finding-body');

      // Meta row
      var metaRow = el('div', 'rv-finding-meta-row');

      var vLabel = el('span', 'rv-verdict-label rv-verdict-label--' + info.cls);
      vLabel.textContent = info.label;
      metaRow.appendChild(vLabel);

      // FABRICATED badge — must be unmistakable
      if (isFake) {
        var fakeBadge = el('span', 'rv-fabricated-badge');
        fakeBadge.textContent = '⚠ FABRICATED — caught';
        metaRow.appendChild(fakeBadge);
      }

      if (f.clause_ref) {
        var clauseEl = el('span', 'rv-clause-ref');
        clauseEl.textContent = '§' + f.clause_ref;
        metaRow.appendChild(clauseEl);
      }

      var confEl = el('span', 'rv-conf-badge');
      confEl.textContent = Math.round((f.confidence || 0) * 100) + '% conf';
      metaRow.appendChild(confEl);

      body.appendChild(metaRow);

      // Claim text (set via textContent — XSS safe)
      var claimEl = el('p', 'rv-finding-claim');
      claimEl.textContent = f.claim;
      body.appendChild(claimEl);

      // Worker
      var workerEl = el('div', 'rv-finding-worker');
      workerEl.textContent = prettyWorker(f.worker);
      body.appendChild(workerEl);

      // Confidence bar
      var barRow = el('div', 'rv-bar-row');
      barRow.appendChild(makeBar(f.confidence, info.barTone));
      body.appendChild(barRow);

      // Evidence quote (only for non-fake findings — fake has no quote)
      if (f.evidence_quote) {
        var quote = el('blockquote', 'rv-evidence-quote rv-evidence-quote--' + info.cls);
        quote.textContent = '“' + f.evidence_quote + '”';
        body.appendChild(quote);
      }

      row.appendChild(body);
      card.appendChild(row);
      list.appendChild(card);
    });

    panel.appendChild(list);
    return panel;
  }

  /* ----------------------------------------------------------
     ⑥ SETTLE BAR
  ---------------------------------------------------------- */

  function renderSettleBar(settlements, done, meta) {
    var panel = el('div', 'rv-panel');

    // Build tx_links map from meta.tx_links for fast lookup
    var txLinkMap = {};
    if (meta && meta.tx_links) {
      meta.tx_links.forEach(function (tx) {
        if (tx.worker && tx.tx_hash) {
          txLinkMap[tx.worker] = tx.tx_hash;
        }
      });
    }

    // Compute totals
    var totalSettled = 0, totalWithheld = 0;
    (settlements || []).forEach(function (s) {
      totalSettled += Number(s.settled_usd) || 0;
      totalWithheld += Math.max(0, (Number(s.authorized_usd) || 0) - (Number(s.settled_usd) || 0));
    });

    // Header
    var header = el('div', 'rv-panel-header');
    var leftCol = el('div');
    var eyebrow = el('div', 'rv-eyebrow rv-eyebrow--gold');
    eyebrow.textContent = 'SETTLEMENT · USDC via x402';
    var title = el('div', 'rv-panel-title');
    title.textContent = '🪙  SETTLEMENT';
    leftCol.appendChild(eyebrow);
    leftCol.appendChild(title);
    header.appendChild(leftCol);

    if (settlements && settlements.length > 0) {
      var totals = el('div', 'rv-settle-totals');
      var settledChip = el('span', 'rv-totals-chip rv-totals-chip--settled');
      settledChip.textContent = '✓ ' + usd(totalSettled);
      totals.appendChild(settledChip);
      var withheldChip = el('span', 'rv-totals-chip rv-totals-chip--withheld');
      withheldChip.textContent = '✗ ' + usd(totalWithheld);
      totals.appendChild(withheldChip);
      header.appendChild(totals);
    }

    panel.appendChild(header);

    if (!settlements || settlements.length === 0) {
      var emp = el('div', 'rv-empty');
      emp.textContent = 'Payments stream here once the verifier rules on each finding — verified work moves money, fabricated work settles at $0.';
      panel.appendChild(emp);
      return panel;
    }

    var cards = el('div', 'rv-settle-cards');

    settlements.forEach(function (s) {
      var paid = Number(s.settled_usd) > 0;
      var fraction = (Number(s.authorized_usd) > 0) ? (Number(s.settled_usd) / Number(s.authorized_usd)) : 0;

      var cardCls = 'rv-settle-card ' + (paid ? 'rv-settle-card--paid' : 'rv-settle-card--withheld');
      var card = el('article', cardCls);

      // Top row: worker name + amount
      var topRow = el('div', 'rv-settle-card-top');

      var workerName = el('div', 'rv-settle-worker');
      workerName.textContent = prettyWorker(s.worker);
      topRow.appendChild(workerName);

      if (paid) {
        var amtEl = el('div', 'rv-settle-amount-paid');
        amtEl.textContent = usd(s.settled_usd);
        topRow.appendChild(amtEl);
      } else {
        var withheldLabel = el('div', 'rv-settle-withheld-label');
        withheldLabel.textContent = '$0 · WITHHELD';
        topRow.appendChild(withheldLabel);
      }
      card.appendChild(topRow);

      // Sub: settled / authorized
      var sub = el('div', 'rv-settle-sub');
      sub.textContent = usd(s.settled_usd) + ' / ' + usd(s.authorized_usd) + ' authorized';
      card.appendChild(sub);

      // Progress bar
      var barRow = el('div', 'rv-bar-row');
      barRow.appendChild(makeBar(paid ? fraction : 0, paid ? 'emerald' : 'red'));
      card.appendChild(barRow);

      // Status + tx link
      var statusRow = el('div', 'rv-settle-status-row');

      var statusText = el('span', 'rv-settle-status-text--' + (paid ? 'paid' : 'withheld'));
      statusText.textContent = s.status || '';
      statusRow.appendChild(statusText);

      // tx_hash: from event data OR meta.tx_links
      var txHash = s.tx_hash || txLinkMap[s.worker] || null;
      if (txHash) {
        var txLink = el('a', 'rv-tx-link');
        txLink.href = 'https://sepolia.basescan.org/tx/' + txHash;
        txLink.target = '_blank';
        txLink.rel = 'noopener noreferrer';
        txLink.textContent = 'tx ↗';
        statusRow.appendChild(txLink);
      } else {
        var noTx = el('span', 'rv-no-tx');
        noTx.textContent = 'no tx';
        statusRow.appendChild(noTx);
      }

      card.appendChild(statusRow);
      cards.appendChild(card);
    });

    panel.appendChild(cards);
    return panel;
  }

  /* ----------------------------------------------------------
     ⑦ RECEIPT
  ---------------------------------------------------------- */

  function renderReceipt(receipt) {
    if (!receipt) return null;

    var panel = el('div', 'rv-panel');

    var header = el('div', 'rv-panel-header');
    var eyebrow = el('div', 'rv-eyebrow');
    eyebrow.textContent = 'CRYPTOGRAPHIC RECEIPT';
    var title = el('div', 'rv-panel-title');
    title.textContent = '🔏  RECEIPT';
    header.appendChild(eyebrow);
    header.appendChild(title);
    panel.appendChild(header);

    var grid = el('div', 'rv-receipt-grid');

    var fields = [
      { label: 'Signer', value: receipt.signer, truncate: false },
      { label: 'Signature', value: truncateHex(receipt.signature), truncate: true },
      { label: 'Deliverable Hash', value: truncateHex(receipt.deliverable_hash), truncate: true },
    ];

    fields.forEach(function (f) {
      var field = el('div', 'rv-receipt-field');
      var label = el('div', 'rv-receipt-field-label');
      label.textContent = f.label;
      var value = el('div', 'rv-receipt-field-value rv-receipt-field-value--mono');
      value.textContent = f.value || '—';
      if (f.truncate) value.title = f.value; // full value in tooltip
      field.appendChild(label);
      field.appendChild(value);
      grid.appendChild(field);
    });

    panel.appendChild(grid);
    return panel;
  }

  /* ----------------------------------------------------------
     ⑧ HERO BANNER
  ---------------------------------------------------------- */

  function renderHero(doneState) {
    if (!doneState) return null;

    var gateOk = doneState.gate_passed;
    var heroClass = 'rv-hero ' + (gateOk ? 'rv-hero--pass' : 'rv-hero--fail');
    var section = el('div', heroClass);
    var inner = el('div', 'rv-hero-inner');

    // Eyebrow
    var eyebrow = el('div', 'rv-hero-eyebrow ' + (gateOk ? 'rv-hero-eyebrow--pass' : 'rv-hero-eyebrow--fail'));
    eyebrow.textContent = (gateOk ? '✓' : '✗') + '  ' + (gateOk ? 'GATE PASSED — WORK VERIFIED' : 'GATE FAILED — FABRICATION CAUGHT');
    inner.appendChild(eyebrow);

    // Big headline
    var headline = el('div', 'rv-hero-headline');

    var amtClass = 'rv-hero-headline-amount ' + (gateOk ? 'rv-hero-headline-amount--pass' : 'rv-hero-headline-amount--fail');
    var amt = el('span', amtClass);

    if (!gateOk && doneState.total_settled_usd === 0) {
      amt.textContent = '$0 paid for fabricated work';
    } else {
      amt.textContent = usd(doneState.total_settled_usd) + ' settled';
    }
    headline.appendChild(amt);
    inner.appendChild(headline);

    // Summary sentence
    if (doneState.catch_summary) {
      var summary = el('p', 'rv-hero-summary');
      summary.textContent = doneState.catch_summary;
      inner.appendChild(summary);
    }

    // Stats row
    var stats = el('div', 'rv-hero-stats');

    var statDefs = [
      { label: 'Total Settled', value: usd(doneState.total_settled_usd), cls: 'rv-hero-stat-value--settled' },
      { label: 'Total Withheld', value: usd(doneState.total_withheld_usd), cls: 'rv-hero-stat-value--withheld' },
      { label: 'Pay Fraction', value: Math.round((doneState.pay_fraction || 0) * 100) + '%', cls: 'rv-hero-stat-value--neutral' },
    ];

    statDefs.forEach(function (sd) {
      var statEl = el('div', 'rv-hero-stat');
      var label = el('div', 'rv-hero-stat-label');
      label.textContent = sd.label;
      var value = el('div', 'rv-hero-stat-value ' + sd.cls);
      value.textContent = sd.value;
      statEl.appendChild(label);
      statEl.appendChild(value);
      stats.appendChild(statEl);
    });

    inner.appendChild(stats);
    section.appendChild(inner);
    return section;
  }

  /* ----------------------------------------------------------
     MAIN — RV.renderApp
  ---------------------------------------------------------- */

  /**
   * RV.renderApp(mountEl, state, meta) -> void
   *
   * Pure idempotent renderer. Clears mountEl and rebuilds the
   * entire panel view from the given RunState + replay meta header.
   * Safe to call every animation frame.
   *
   * @param {Element} mountEl  - DOM node to render into
   * @param {Object}  state    - RunState (from RV.initialState / RV.applyEvent)
   * @param {Object}  meta     - Replay header minus events
   */
  function renderApp(mountEl, state, meta) {
    if (!mountEl) return;

    // Idempotent clear
    mountEl.innerHTML = '';

    // Ensure the root carries the rv-app class for scoped styles
    if (!mountEl.classList.contains('rv-app')) {
      mountEl.classList.add('rv-app');
    }

    var s = state || {};
    var m = meta || {};

    // ① Header (always)
    mountEl.appendChild(renderHeader(m));

    // Layout wrapper
    var layout = el('div', 'rv-layout');
    layout.style.paddingTop = '28px';

    // ⑧ HERO banner — shown first when done so the catch is UNMISSABLE
    if (s.done) {
      var hero = renderHero(s.done);
      if (hero) layout.appendChild(hero);
    }

    // ② StageBar
    if (s.stages && s.stages.length > 0) {
      layout.appendChild(renderStageBar(s.stages));
    }

    // ③ BidFeed — show once pool or bids exist
    if ((s.pool && s.pool.length > 0) || (s.bids && s.bids.length > 0)) {
      layout.appendChild(renderBidFeed(s.pool || [], s.bids || [], s.hire || null, s.hiredWorkers || new Set()));
    }

    // ④ WorkRoom — show once room has messages
    if (s.room && s.room.length > 0) {
      layout.appendChild(renderWorkRoom(s.room));
    }

    // ⑤ Findings — show once any finding exists
    if (s.findings && s.findings.length > 0) {
      layout.appendChild(renderFindings(s.findings));
    }

    // ⑥ SettleBar — show once any settlement exists
    if (s.settlements && s.settlements.length > 0) {
      layout.appendChild(renderSettleBar(s.settlements, s.done, m));
    }

    // ⑦ Receipt — show once receipt is available
    if (s.receipt) {
      var receiptPanel = renderReceipt(s.receipt);
      if (receiptPanel) layout.appendChild(receiptPanel);
    }

    mountEl.appendChild(layout);
  }

  /* Attach to global namespace */
  global.RV.renderApp = renderApp;

}(typeof window !== 'undefined' ? window : globalThis));
