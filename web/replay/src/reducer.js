/**
 * RV.reducer — vanilla JS port of web/lib/runState.ts
 *
 * Attaches to the global RV namespace (window.RV in a browser, globalThis.RV in Node).
 * No import/export, no bundler, no dependencies.
 *
 * Exposed:
 *   RV.initialState()              -> RunState
 *   RV.applyEvent(state, ev)       -> RunState  (pure — returns new state)
 *   RV.settledTotals(settlements)  -> { settled, withheld }
 */
(function (global) {
  global.RV = global.RV || {};

  var STAGE_ORDER = [
    "Post",
    "Discover",
    "Bid",
    "Hire",
    "Work",
    "Verify",
    "Settle",
    "Done",
  ];

  /**
   * Mirror of initialState() in runState.ts.
   * hiredWorkers is a Set, room is an array, _roomSeq is a number.
   */
  function initialState() {
    return {
      running: false,
      finished: false,
      error: null,
      stages: STAGE_ORDER.map(function (name) {
        return { name: name, status: "pending" };
      }),
      document: null,
      pool: [],
      bids: [],
      hire: null,
      hiredWorkers: new Set(),
      room: [],
      findings: [],
      settlements: [],
      receipt: null,
      done: null,
      _roomSeq: 0,
    };
  }

  /**
   * Pure upsert helper — mirrors upsertStage() in runState.ts.
   * Returns a new array; never mutates input.
   */
  function upsertStage(stages, next) {
    var idx = -1;
    for (var i = 0; i < stages.length; i++) {
      if (stages[i].name === next.name) {
        idx = i;
        break;
      }
    }
    if (idx === -1) {
      return stages.concat([next]);
    }
    var copy = stages.slice();
    copy[idx] = next;
    return copy;
  }

  /**
   * Pure reducer — mirror of applyEvent() in runState.ts.
   * ev = { type, data }  (seq / t_offset_ms stripped by the player).
   * Returns a NEW state object; never mutates prev.
   */
  function applyEvent(prev, ev) {
    switch (ev.type) {
      case "stage":
        return Object.assign({}, prev, {
          stages: upsertStage(prev.stages, ev.data),
        });

      case "document":
        return Object.assign({}, prev, { document: ev.data });

      case "pool":
        return Object.assign({}, prev, { pool: ev.data.agents });

      case "bid":
        return Object.assign({}, prev, {
          bids: prev.bids.concat([ev.data]),
        });

      case "hire": {
        var hire = ev.data;
        var newWorkers = new Set(
          hire.hired.map(function (h) {
            return h.worker;
          })
        );
        return Object.assign({}, prev, {
          hire: hire,
          hiredWorkers: newWorkers,
        });
      }

      case "room_message": {
        var line = Object.assign({}, ev.data, { id: prev._roomSeq });
        return Object.assign({}, prev, {
          room: prev.room.concat([line]),
          _roomSeq: prev._roomSeq + 1,
        });
      }

      case "finding":
        return Object.assign({}, prev, {
          findings: prev.findings.concat([ev.data]),
        });

      case "settle":
        return Object.assign({}, prev, {
          settlements: prev.settlements.concat([ev.data]),
        });

      case "receipt":
        return Object.assign({}, prev, { receipt: ev.data });

      case "done":
        return Object.assign({}, prev, {
          done: ev.data,
          running: false,
          finished: true,
        });

      case "error":
        return Object.assign({}, prev, {
          error: ev.data.message,
          running: false,
        });

      default:
        return prev;
    }
  }

  /**
   * Port of settledTotals() in runState.ts.
   * settlements: SettleEvent[]
   * Returns { settled: number, withheld: number }
   */
  function settledTotals(settlements) {
    var settled = 0;
    var withheld = 0;
    for (var i = 0; i < settlements.length; i++) {
      var s = settlements[i];
      settled += s.settled_usd;
      withheld += Math.max(0, s.authorized_usd - s.settled_usd);
    }
    return { settled: settled, withheld: withheld };
  }

  // Attach to the global RV namespace
  global.RV.initialState = initialState;
  global.RV.applyEvent = applyEvent;
  global.RV.settledTotals = settledTotals;
})(typeof window !== "undefined" ? window : globalThis);
