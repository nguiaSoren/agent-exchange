(function (global) {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────────
  var _meta   = null;   // replay header (everything except .events)
  var _events = [];     // events[]
  var _cursor = -1;     // -1 = before first event
  var _playing = false;
  var _speed  = 1;      // 0.5 | 1 | 2 | 4
  var _timer  = null;   // setTimeout handle

  // ── Event-type beat durations (ms at 1×) ──────────────────────────────────
  var BEATS = {
    stage:        700,
    settle:       600,
    bid:          350,
    finding:      350,
    room_message: 350,
    // everything else:
    _default:     450
  };

  function beatFor(eventType) {
    return (BEATS[eventType] || BEATS._default);
  }

  // ── DOM helpers ────────────────────────────────────────────────────────────
  function $id(id) { return document.getElementById(id); }

  function setText(el, text) {
    if (el) el.textContent = text;
  }

  // ── Fold: compute state at cursor ─────────────────────────────────────────
  function computeState() {
    if (!_events || _events.length === 0) return RV.initialState();
    var slice = _events.slice(0, _cursor + 1);
    return slice.reduce(function (s, e) {
      return RV.applyEvent(s, { type: e.type, data: e.data });
    }, RV.initialState());
  }

  // ── Render the app + update transport UI ──────────────────────────────────
  function render() {
    var mountEl = $id('rv-app');
    if (!mountEl || !_meta) return;
    var state = computeState();
    RV.renderApp(mountEl, state, _meta);
    updateControls();
  }

  function updateControls() {
    var n = _events ? _events.length : 0;

    // Scrubber
    var scrubber = $id('rv-scrubber');
    if (scrubber) {
      scrubber.max   = Math.max(0, n - 1);
      scrubber.value = Math.max(0, _cursor);
      scrubber.disabled = (n === 0);
    }

    // Step readout
    var readout = $id('rv-step-readout');
    if (readout) {
      if (_cursor < 0 || n === 0) {
        setText(readout, 'step — / ' + n);
      } else {
        var ev = _events[_cursor];
        setText(readout, 'step ' + (_cursor + 1) + ' / ' + n + ' — ' + ev.type);
      }
    }

    // Play-pause button label
    var btnPlay = $id('rv-btn-play');
    if (btnPlay) btnPlay.textContent = _playing ? '⏸ pause' : '▶ play';

    // Speed button label
    var btnSpeed = $id('rv-btn-speed');
    if (btnSpeed) btnSpeed.textContent = _speed + '×';
  }

  // ── Cursor movement ────────────────────────────────────────────────────────
  function setCursor(c) {
    var n = _events ? _events.length : 0;
    _cursor = Math.max(-1, Math.min(n - 1, c));
    render();
  }

  function stepBack() {
    stopPlay();
    setCursor(_cursor - 1);
  }

  function stepForward() {
    stopPlay();
    setCursor(_cursor + 1);
  }

  // ── Playback engine ───────────────────────────────────────────────────────
  function stopPlay() {
    _playing = false;
    if (_timer !== null) { clearTimeout(_timer); _timer = null; }
    updateControls();
  }

  function startPlay() {
    var n = _events ? _events.length : 0;
    if (n === 0) return;
    // If already at end, restart from beginning
    if (_cursor >= n - 1) {
      _cursor = -1;
      render();
    }
    _playing = true;
    updateControls();
    scheduleNext();
  }

  function scheduleNext() {
    if (!_playing) return;
    var n = _events ? _events.length : 0;
    if (_cursor >= n - 1) {
      // reached end
      stopPlay();
      return;
    }
    // Beat is keyed to the NEXT event's type
    var nextEv = _events[_cursor + 1];
    var delay  = beatFor(nextEv ? nextEv.type : '_default') / _speed;
    _timer = setTimeout(function () {
      _timer = null;
      if (!_playing) return;
      _cursor = Math.min(_cursor + 1, n - 1);
      render();
      scheduleNext();
    }, delay);
  }

  function togglePlay() {
    if (_playing) {
      stopPlay();
    } else {
      startPlay();
    }
  }

  function toggleSpeed() {
    var speeds = [0.5, 1, 2, 4];
    var idx = speeds.indexOf(_speed);
    _speed = speeds[(idx + 1) % speeds.length];
    // If playing, the next scheduleNext call will use the new speed automatically
    updateControls();
  }

  // ── "Jump to the catch" ────────────────────────────────────────────────────
  function jumpToCatch() {
    stopPlay();
    if (!_events) return;
    for (var i = 0; i < _events.length; i++) {
      var ev = _events[i];
      if (ev.type === 'finding' && ev.data && ev.data.verdict === 'unsupported') {
        setCursor(i);
        return;
      }
    }
    // No catch found — do nothing (guard)
  }

  // ── Load a replay object ──────────────────────────────────────────────────
  function loadReplay(obj) {
    if (!obj || typeof obj !== 'object') return false;
    if (typeof obj.schema !== 'string' ||
        !obj.schema.startsWith('agent-exchange.replay/')) return false;
    if (!Array.isArray(obj.events)) return false;

    _events = obj.events;
    // meta = everything except events
    _meta = {};
    for (var k in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, k) && k !== 'events') {
        _meta[k] = obj[k];
      }
    }
    _cursor = -1;
    _playing = false;
    if (_timer !== null) { clearTimeout(_timer); _timer = null; }

    // Hide loader, show app & controls
    var drop = $id('rv-drop');
    if (drop) drop.style.display = 'none';
    var app  = $id('rv-app');
    if (app)  app.style.display  = '';
    var ctl  = $id('rv-controls');
    if (ctl)  ctl.style.display  = '';

    buildControls();
    render();
    return true;
  }

  // ── Build transport UI ────────────────────────────────────────────────────
  function buildControls() {
    var ctl = $id('rv-controls');
    if (!ctl) return;
    var n = _events ? _events.length : 0;

    ctl.innerHTML = [
      '<div class="rv-ctl-bar">',
        '<button class="rv-ctl-btn" id="rv-btn-back" title="Step back">◀ back</button>',
        '<button class="rv-ctl-btn rv-ctl-btn--primary" id="rv-btn-play" title="Play / Pause">▶ play</button>',
        '<button class="rv-ctl-btn" id="rv-btn-fwd"  title="Step forward">fwd ▶▶</button>',
        '<input  class="rv-ctl-scrubber" type="range" id="rv-scrubber"',
                ' min="0" max="' + Math.max(0, n - 1) + '" value="0"',
                ' step="1">',
        '<button class="rv-ctl-btn rv-ctl-btn--speed" id="rv-btn-speed" title="Playback speed">1×</button>',
        '<button class="rv-ctl-btn rv-ctl-btn--catch" id="rv-btn-catch" title="Jump to the unsupported finding">',
          '⏭ Jump to the catch',
        '</button>',
        '<span class="rv-ctl-readout" id="rv-step-readout">step — / ' + n + '</span>',
      '</div>'
    ].join('');

    // Wire events
    var btnBack  = $id('rv-btn-back');
    var btnPlay  = $id('rv-btn-play');
    var btnFwd   = $id('rv-btn-fwd');
    var btnSpeed = $id('rv-btn-speed');
    var btnCatch = $id('rv-btn-catch');
    var scrubber = $id('rv-scrubber');

    if (btnBack)  btnBack.addEventListener('click',  stepBack);
    if (btnPlay)  btnPlay.addEventListener('click',  togglePlay);
    if (btnFwd)   btnFwd.addEventListener('click',   stepForward);
    if (btnSpeed) btnSpeed.addEventListener('click', toggleSpeed);
    if (btnCatch) btnCatch.addEventListener('click', jumpToCatch);

    if (scrubber) {
      scrubber.addEventListener('input', function () {
        stopPlay();
        setCursor(parseInt(scrubber.value, 10));
      });
    }

    updateControls();
  }

  // ── Drag-drop / file-picker loader ───────────────────────────────────────
  function handleFile(file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      var text = e.target.result;
      var obj;
      try { obj = JSON.parse(text); } catch (_) {
        alert('Could not parse JSON: ' + file.name);
        return;
      }
      if (!loadReplay(obj)) {
        alert('Not a valid agent-exchange replay file: ' + file.name);
      }
    };
    reader.readAsText(file);
  }

  function wireDrop() {
    var dropZone = $id('rv-drop');
    if (!dropZone) return;

    dropZone.style.display = '';

    // Hidden file input
    var fileInput = document.createElement('input');
    fileInput.type    = 'file';
    fileInput.accept  = '.json';
    fileInput.style.display = 'none';
    fileInput.id      = 'rv-file-input';
    document.body.appendChild(fileInput);

    fileInput.addEventListener('change', function () {
      if (fileInput.files && fileInput.files[0]) handleFile(fileInput.files[0]);
    });

    // Click the drop zone to open picker
    dropZone.addEventListener('click', function () {
      fileInput.click();
    });

    // Drag-over styling
    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropZone.classList.add('rv-ctl-drop--hover');
    });

    dropZone.addEventListener('dragleave', function () {
      dropZone.classList.remove('rv-ctl-drop--hover');
    });

    // Drop
    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.classList.remove('rv-ctl-drop--hover');
      var dt = e.dataTransfer;
      if (dt && dt.files && dt.files[0]) handleFile(dt.files[0]);
    });
  }

  // ── Bootstrap on DOMContentLoaded ────────────────────────────────────────
  function init() {
    // Hide app & controls until replay loaded
    var app = $id('rv-app');
    var ctl = $id('rv-controls');
    if (app) app.style.display  = 'none';
    if (ctl) ctl.style.display  = 'none';

    // Read inline data slot
    var dataEl = $id('rv-data');
    var inlineObj = null;
    if (dataEl) {
      var raw = dataEl.textContent || '';
      try { inlineObj = JSON.parse(raw.trim()); } catch (_) { inlineObj = null; }
    }

    if (inlineObj !== null &&
        typeof inlineObj === 'object' &&
        typeof inlineObj.schema === 'string' &&
        inlineObj.schema.startsWith('agent-exchange.replay/')) {
      loadReplay(inlineObj);
    } else {
      // No inline data — show drop zone
      wireDrop();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose minimal API on RV namespace for potential external use
  if (!global.RV) global.RV = {};
  global.RV._player = {
    loadReplay: loadReplay,
    setCursor:  setCursor,
    play:       startPlay,
    stop:       stopPlay
  };

})(typeof window !== 'undefined' ? window : globalThis);
