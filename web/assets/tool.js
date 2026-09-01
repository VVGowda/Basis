/* ============================================================
   Basis - the eligibility tool

   Loads only on the page that carries the form. Posts to
   /api/match and renders the response into the results column.

   No inline styles anywhere: the Content Security Policy forbids
   them, which is what lets style-src stay strict on a page where
   people type an income and a credit score.
   ============================================================ */

(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  // The section wrapper is #finder; the form itself is #finder-form. Binding
  // the submit handler to the section would silently never fire.
  var form = $("finder-form");
  if (!form) return;

  var results = $("results");
  var submitBtn = $("submit");
  var esc = (window.LM && window.LM.esc) || function (s) { return String(s); };

  /* ---------- formatting ---------- */
  function usd(n, dp) {
    if (n === null || n === undefined) return "n/a";
    return "$" + Number(n).toLocaleString("en-US", {
      minimumFractionDigits: dp || 0, maximumFractionDigits: dp || 0,
    });
  }
  function compactUsd(n) {
    if (!n) return "n/a";
    if (n >= 1e12) return "$" + (n / 1e12).toFixed(2) + "T";
    if (n >= 1e9) return "$" + (n / 1e9).toFixed(1) + "B";
    if (n >= 1e6) return "$" + (n / 1e6).toFixed(0) + "M";
    return usd(n);
  }

  // Checks carry either a pre-formatted string ("40.58 percent") or a raw
  // number. Only the loan-amount check is money: formatting every number as
  // currency turns a credit score of 700 into "$700".
  function checkValue(checkId, v) {
    if (typeof v === "number" && checkId === "amount") return usd(v);
    return v;
  }

  var VERDICT = {
    likely_eligible: ["Likely eligible", "pass"],
    possible: ["Possible, with conditions", "warn"],
    not_eligible: ["Not eligible", "fail"],
  };
  var MARK = { pass: "✓", warn: "!", fail: "✗" };

  // Internal source keys are plumbing. Readers get the authority behind the
  // figure instead, which is both more meaningful and more credible.
  var SOURCE_LABEL = {
    fdic_institutions: "FDIC bank register",
    fdic_locations: "FDIC branch records",
    cfpb: "CFPB complaint records",
    cfpb_suggest: "CFPB complaint records",
    treasury: "US Treasury rates",
    frankfurter: "ECB exchange rates",
    zippopotam: "US postal geography",
    nager: "Federal holiday calendar",
    worldbank: "World Bank indicators",
    ifsc: "Indian branch directory",
  };

  function sourceLabel(key) {
    return SOURCE_LABEL[key] || "Reference data";
  }

  /* ---------- purpose-driven form ---------- */
  var assetField = $("asset-field");
  var assetLabel = assetField.querySelector("label");

  function toggle(el, shown) { if (el) el.classList.toggle("hidden", !shown); }

  function syncPurpose() {
    var p = $("purpose").value;
    var isProperty = p === "home_purchase" || p === "home_refinance";
    var isAuto = p === "auto";

    toggle(assetField, isProperty || isAuto);
    if (isProperty) assetLabel.textContent = "Price of the home";
    else if (isAuto) assetLabel.textContent = "Price of the vehicle";

    toggle($("military_service").closest(".chk"), isProperty);
    toggle($("rural_property").closest(".chk"), p === "home_purchase");
    toggle($("business_operating").closest(".chk"), p === "small_business");
  }
  $("purpose").addEventListener("change", syncPurpose);
  syncPurpose();

  /* ---------- submit ---------- */
  form.addEventListener("submit", function (ev) { ev.preventDefault(); run(); });

  function payload() {
    var body = {
      purpose: $("purpose").value,
      annual_income: Number($("annual_income").value),
      income_currency: $("income_currency").value,
      monthly_debt: Number($("monthly_debt").value || 0),
      credit_score: Number($("credit_score").value),
      loan_amount: Number($("loan_amount").value),
      down_payment: Number($("down_payment").value || 0),
      military_service: $("military_service").checked,
      rural_property: $("rural_property").checked,
      business_operating: $("business_operating").checked,
    };
    var asset = $("asset_value").value;
    if (asset !== "" && !assetField.classList.contains("hidden")) {
      body.asset_value = Number(asset);
    }
    var zip = $("zip_code").value.trim();
    if (zip) body.zip_code = zip;
    return body;
  }

  function run() {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spin"></span>Checking federal records';
    results.innerHTML =
      '<div class="empty"><h3>Working</h3><p>Reading FDIC institution records, ' +
      "CFPB complaint history and current Treasury rates.</p></div>";

    fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      })
      .then(function (res) {
        if (!res.ok) throw new Error(describeError(res.data));
        render(res.data);
      })
      .catch(function (err) {
        results.innerHTML =
          '<div class="notice notice--warn"><h3>Could not complete the check</h3><p>' +
          esc(err.message) + "</p></div>";
      })
      .finally(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = "Show my options";
      });
  }

  function describeError(data) {
    if (!data) return "The server did not respond.";
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map(function (d) {
          var field = (d.loc || []).slice(-1)[0];
          return (field ? field + ": " : "") + d.msg;
        })
        .join(" · ");
    }
    return "Unexpected response from the server.";
  }

  /* ---------- render ---------- */
  function render(d) {
    results.innerHTML =
      standingNotice() +
      degradedNotice(d) +
      summary(d) +
      ceiling(d) +
      programs(d) +
      lenders(d) +
      closing(d);

    Array.prototype.forEach.call(results.querySelectorAll(".prog-head"), function (head) {
      head.addEventListener("click", function () {
        var card = head.parentNode;
        var open = card.classList.toggle("open");
        head.setAttribute("aria-expanded", String(open));
      });
    });

    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function standingNotice() {
    // One line, not a manifesto. Enough to be straight with people, short
    // enough that it does not bury the answer they came for.
    return (
      '<div class="notice"><h3>How to read this</h3>' +
      "<p>Estimates from published program rules and live federal data, not a credit " +
      "decision. The banks below are real and serve your area; confirm rates and terms " +
      "with them directly.</p></div>"
    );
  }

  function degradedNotice(d) {
    var failed = (d.sources_used || []).filter(function (s) { return !s.ok; });
    if (!failed.length) return "";
    var names = failed
      .map(function (s) { return s.source; })
      .filter(function (v, i, a) { return a.indexOf(v) === i; });
    return (
      '<div class="notice notice--warn"><h3>Some sources did not respond</h3><p>' +
      esc(names.map(sourceLabel).join(", ")) + ". Anything depending on " +
      (names.length === 1 ? "it" : "them") +
      " is missing from this answer rather than estimated. Everything else is unaffected.</p></div>"
    );
  }

  function summary(d) {
    var a = d.applicant, e = d.eligibility, best = e.best, loc = d.location;

    var cells = [
      { k: "Credit band", v: a.credit_band, s: a.credit_score + " entered" },
      {
        k: "Programs open",
        v: e.eligible_count + " of " + e.programs.length,
        s: e.eligible_count ? "at least one path forward" : "nothing clears at these numbers",
      },
      {
        k: "Best monthly",
        v: best ? usd(best.estimate.total_monthly) : "n/a",
        s: best ? best.name + " at " + best.estimate.rate_pct + "%" : "no qualifying program",
      },
      {
        k: "Location",
        v: loc ? loc.state_abbr : "not set",
        s: loc ? loc.city : "add a ZIP for lender matching",
      },
    ];

    var out =
      '<div class="res-head"><h2>Where you stand</h2><span class="meta">Benchmark ' +
      d.benchmark.rate + "% · " + esc(d.benchmark.label) +
      (d.benchmark.as_of ? " · " + esc(d.benchmark.as_of) : "") + "</span></div>";

    out += '<div class="stat-row">';
    cells.forEach(function (c) {
      out +=
        '<div class="stat-cell"><div class="k">' + esc(c.k) + "</div>" +
        '<div class="v">' + esc(c.v) + '</div><div class="s">' + esc(c.s) + "</div></div>";
    });
    out += "</div>";

    var conv = a.currency_conversion;
    if (conv && conv.converted) {
      out +=
        '<p class="fine">All amounts converted from ' + esc(conv.currency) + " at " +
        conv.rate + " USD" + (conv.as_of ? " (" + esc(conv.as_of) + ")" : "") +
        ". Income becomes " + usd(conv.usd) + " a year, and the loan becomes " +
        usd(a.loan_amount_usd) + ".</p>";
    } else if (conv && conv.warning) {
      out += '<p class="assume">' + esc(conv.warning) + "</p>";
    }
    return out;
  }

  function ceiling(d) {
    var af = d.eligibility.affordability;
    if (!af || !af.max_loan_usd) return "";

    var asked = d.applicant.loan_amount_usd;
    var short = af.max_loan_usd < asked;

    var out =
      '<div class="ceiling"><div class="k">What your income and debts could carry</div>' +
      '<div class="big">' + usd(af.max_loan_usd) + "</div>";

    out +=
      "<p>Based on income and existing debts alone, before any deposit or program rule. " +
      "Capped by " + esc(af.limited_by || "your debt-to-income limit") + ", using " +
      esc(af.program_name) + " terms over " + Math.round(af.term_months / 12) +
      " years at an estimated " + af.rate_pct + "%. That is roughly " +
      usd(af.monthly_budget_usd) + " a month of payment room." +
      (af.note ? " " + esc(af.note) : "") + "</p>";

    if (short) {
      out +=
        "<p><strong>You asked about " + usd(asked) + ", which is " +
        usd(asked - af.max_loan_usd) + " above that.</strong> Borrowing less, clearing " +
        "existing debt, or adding a co-borrower are the levers that move this number.</p>";
    }

    out +=
      "<p>This measures capacity, not approval. A program can carry the most here and still " +
      "need a larger deposit to qualify below.</p>";

    return out + "</div>";
  }

  function programs(d) {
    var out =
      '<div class="res-head"><h2>Loan programs</h2>' +
      '<span class="meta">Open any program to see every check</span></div>';

    d.eligibility.programs.forEach(function (p) {
      var v = VERDICT[p.verdict], est = p.estimate;

      out += '<article class="prog" data-v="' + esc(p.verdict) + '">';
      out += '<button class="prog-head" type="button" aria-expanded="false">';
      out +=
        '<span class="prog-title"><h3>' + esc(p.name) +
        ' <span class="tag tag--' + v[1] + '">' + v[0] + "</span></h3>" +
        '<span class="sum">' + esc(p.summary) + "</span></span>";
      out +=
        '<span class="prog-price"><span class="amt">' + usd(est.total_monthly) + "</span>" +
        '<span class="per">per month</span>' +
        '<span class="rt">' + est.rate_pct + "% over " +
        Math.round(est.term_months / 12) + " yr</span></span>";
      out += "</button>";

      out += '<div class="prog-body">';

      out += '<h4>Checks</h4><ul class="checks">';
      p.checks.forEach(function (c) {
        out +=
          '<li><span class="mk mk--' + esc(c.status) + '">' + MARK[c.status] + "</span><div>" +
          '<div class="cl">' + esc(c.label) + "</div>" +
          '<div class="cd">' + esc(c.detail) + "</div>";
        if (c.your_value !== null && c.your_value !== undefined) {
          out +=
            '<div class="cv">You: ' + esc(checkValue(c.id, c.your_value)) +
            (c.threshold !== null && c.threshold !== undefined
              ? "  ·  Limit: " + esc(checkValue(c.id, c.threshold)) : "") + "</div>";
        }
        out += "</div></li>";
      });
      out += "</ul>";

      out += '<h4>Estimated monthly cost</h4><table class="cost">';
      out += "<tr><td>Principal and interest</td><td>" + usd(est.principal_and_interest) + "</td></tr>";
      if (est.escrow_estimate) {
        out += '<tr class="sub"><td>Property tax and insurance, estimated</td><td>' + usd(est.escrow_estimate) + "</td></tr>";
      }
      if (est.mortgage_insurance) {
        out += '<tr class="sub"><td>Mortgage insurance</td><td>' + usd(est.mortgage_insurance) + "</td></tr>";
      }
      out += "<tr><td>Total monthly</td><td>" + usd(est.total_monthly) + "</td></tr></table>";

      out +=
        '<p class="fine">Rate built as ' + est.rate_breakdown.benchmark + "% benchmark + " +
        est.rate_breakdown.program_spread + " program spread " +
        (est.rate_breakdown.credit_adjustment >= 0 ? "+ " : "- ") +
        Math.abs(est.rate_breakdown.credit_adjustment) +
        " credit adjustment. Total interest over the full term: " + usd(est.total_interest) + ".</p>";

      if (p.requirements && p.requirements.length) {
        out += '<h4>Also required</h4><ul class="bullets">';
        p.requirements.forEach(function (r) { out += "<li>" + esc(r) + "</li>"; });
        out += "</ul>";
      }
      if (p.tradeoffs && p.tradeoffs.length) {
        out += '<h4>Worth knowing</h4><ul class="bullets">';
        p.tradeoffs.forEach(function (t) { out += "<li>" + esc(t) + "</li>"; });
        out += "</ul>";
      }

      out += '<p class="fine">Criteria from: ' + esc(p.authority) + "</p>";
      if (p.assumption) out += '<div class="assume">' + esc(p.assumption) + "</div>";

      out += "</div></article>";
    });

    return out;
  }

  function lenders(d) {
    var L = d.lenders || {};
    var list = L.lenders || [];

    var meta = "";
    if (L.state_institutions_found !== undefined) {
      meta = L.state_institutions_found + " institutions in state · " +
        L.branches_found_in_zip + " branches in your ZIP";
    }

    var out = '<div class="res-head"><h2>Banks that serve you</h2><span class="meta">' + esc(meta) + "</span></div>";

    if (!list.length) {
      out +=
        '<div class="lender-note' + (L.degraded ? " lender-note--warn" : "") + '">' +
        (L.degraded ? "<strong>Temporarily unavailable.</strong> " : "") +
        esc(L.note || "No institutions were returned for this location.") + "</div>";
      return out;
    }

    out +=
      '<p class="fine">Real FDIC-insured institutions, ranked by branches near you and their ' +
      "CFPB complaint record. FDIC does not publish which loan programs a bank originates, so " +
      "product fit is inferred from institution size. Call and confirm.</p>";

    list.forEach(function (b) {
      out += '<div class="lender"><div>';
      out += "<h3>" + esc(b.name) + "</h3>";
      out +=
        '<div class="loc">' + esc(b.city || "") +
        (b.state_abbr ? ", " + esc(b.state_abbr) : "") +
        " · FDIC cert " + esc(b.cert) + "</div>";

      out += '<ul class="why">';
      (b.why || []).forEach(function (w) { out += "<li>" + esc(w) + "</li>"; });
      if (b.complaint_rate) {
        out += "<li>" + b.complaint_rate.per_billion_assets + " complaints per $1B assets</li>";
      }
      var prof = b.complaints || {};
      if (prof.matched && prof.origination_complaints !== null && prof.origination_complaints !== undefined) {
        out += "<li>" + Number(prof.origination_complaints).toLocaleString("en-US") +
          " about applying for a loan</li>";
      }
      out += "</ul>";

      if (b.nearest_branch) {
        out +=
          '<div class="branch">Nearest branch on file: ' + esc(b.nearest_branch.address) +
          ", " + esc(b.nearest_branch.city) + " " + esc(b.nearest_branch.zip) + "</div>";
      }
      out += "</div>";

      out += '<div class="side">';
      out += '<div class="assets">' + compactUsd(b.assets_usd) + "<small>total assets</small></div>";
      out += '<span class="tag tag--ghost">' + esc(b.scale) + "</span>";
      if (b.website) {
        out += '<a class="visit" href="' + esc(b.website) + '" rel="noopener nofollow" target="_blank">Visit site</a>';
      }
      out += "</div></div>";
    });

    return out;
  }

  function closing(d) {
    var out = "";

    if (d.funding_estimate && d.funding_estimate.date) {
      var f = d.funding_estimate;
      out += '<div class="res-head"><h2>If you started today</h2></div>';
      out +=
        '<div class="ceiling"><div class="k">Typical funding date</div>' +
        '<div class="big">' + esc(f.date) + "</div><p>" +
        f.typical_business_days + " business days is the usual timeline for this loan type. " +
        (f.holidays_skipped && f.holidays_skipped.length
          ? "Skipped " + f.holidays_skipped.length + " US bank holiday" +
            (f.holidays_skipped.length === 1 ? "" : "s") + " along the way. "
          : "") +
        "Not a commitment from any lender.</p></div>";
    }

    out += '<div class="res-head"><h2>Behind this answer</h2></div>';
    out += '<div class="chips">';
    var seen = {};
    (d.sources_used || []).forEach(function (s) {
      var label = sourceLabel(s.source);
      var key = label + "|" + s.ok + "|" + s.cached;
      if (seen[key]) return;
      seen[key] = true;
      var cls = !s.ok ? "chip--bad" : s.cached ? "" : "chip--live";
      var suffix = !s.ok ? " unavailable" : s.cached ? " cached" : " live";
      out += '<span class="chip ' + cls + '">' + esc(label) + suffix + "</span>";
    });
    out += "</div>";

    out +=
      '<div class="callout"><h3>Take this to a lender</h3><p>' +
      "You now have the programs you qualify for, what each costs, and the institutions near " +
      "you that write them. Call two or three and ask them to price the program named above. " +
      "Rates here are modelled from the current Treasury benchmark, so treat them as the " +
      "opening position rather than the final number.</p></div>";

    return out;
  }
})();
