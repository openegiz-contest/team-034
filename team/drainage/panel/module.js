/*
 * Drainage panel for the «Кварцитовые Горки» twin (horizon 420 m).
 *
 * Plain SystemJS module: Grafana supplies React and its SDK, no build step.
 * Reads the twins sump-01, pump-01, pump-02 from Ditto through the OpenEgiz
 * app's plugin proxy (no Ditto password in the browser) and draws the
 * drainage as a cross-section: inflow -> sump -> pumps -> riser in the shaft
 * -> surface. Buttons write the "control" features of the twins; the
 * simulator reads them from Ditto and the panel shows the result only when
 * the twins confirm it.
 */
System.register(['react', '@grafana/data', '@grafana/runtime'], function (exports) {
  'use strict';
  var React, PanelPlugin, runtime;
  return {
    setters: [function (m) { React = m; }, function (m) { PanelPlugin = m.PanelPlugin; }, function (m) { runtime = m; }],
    execute: function () {
      var h = React.createElement;
      var NS = 'org.kvgorki:';
      var IDS = ['sump-01', 'pump-01', 'pump-02'];
      var PUMPS = [{id: 'pump-01', label: 'Н-1'}, {id: 'pump-02', label: 'Н-2'}];
      var BASE = 'api/plugin-proxy/ertis-opentwins-app/ditto/api/2/things';
      var C = {
        water: '#3d8fd6', pipe: '#8a8f98', run: '#56a64b', stop: '#7b7f87',
        warn: '#f0a03c', alarm: '#e5534b', rock: 'rgba(150,125,100,0.16)', void: 'rgba(0,0,0,0.28)'
      };

      function request(method, path, data) {
        return new Promise(function (resolve, reject) {
          runtime.getBackendSrv().fetch({url: BASE + path, method: method, data: data, showErrorAlert: false,
            timeout: 7000, headers: {'Cache-Control': 'no-cache'}}).subscribe({
            next: function (response) { resolve(response.data); }, error: reject
          });
        });
      }
      function errorText(error) {
        return error && error.data && (error.data.message || error.data.description) || error && error.message || 'Не удалось обратиться к OpenEgiz';
      }
      function v(twins, id, feature) {
        var t = twins && twins[id];
        var f = t && t.features && t.features[feature];
        return f && f.properties ? f.properties.value : undefined;
      }
      function control(twins, id, key) {
        var t = twins && twins[id];
        var f = t && t.features && t.features.control;
        return f && f.properties ? f.properties[key] : undefined;
      }
      function attr(twins, id, key) {
        var t = twins && twins[id];
        return t && t.attributes ? t.attributes[key] : undefined;
      }
      function num(x, digits) {
        return typeof x === 'number' && isFinite(x)
          ? x.toLocaleString('ru-RU', {maximumFractionDigits: digits === undefined ? 0 : digits}) : '—';
      }
      function hoursText(x) {
        if (typeof x !== 'number' || !isFinite(x)) { return '—'; }
        var hh = Math.floor(x), mm = Math.round((x - hh) * 60);
        if (mm === 60) { hh += 1; mm = 0; }
        return hh + ' ч ' + mm + ' мин';
      }

      // Animated dashes along a pipe while water flows.
      function flowLine(d, active, width, color) {
        return [
          h('path', {key: 'p', d: d, fill: 'none', stroke: C.pipe, strokeWidth: width + 4, strokeLinejoin: 'round'}),
          h('path', {key: 'f', d: d, fill: 'none', stroke: active ? color : 'transparent', strokeWidth: width,
            strokeDasharray: '10 8', strokeLinejoin: 'round'},
            active ? h('animate', {attributeName: 'stroke-dashoffset', from: '18', to: '0', dur: '0.6s', repeatCount: 'indefinite'}) : null)
        ];
      }

      function Schematic(props) {
        var t = props.twins, fresh = props.fresh;
        var fill = Math.max(0, Math.min(100, v(t, 'sump-01', 'fill_pct') || 0));
        var inflow = v(t, 'sump-01', 'inflow') || 0;
        var outflow = v(t, 'sump-01', 'outflow') || 0;
        var warnPct = attr(t, 'sump-01', 'warning_pct') || 60;
        var alarmPct = attr(t, 'sump-01', 'alarm_pct') || 80;
        var state = v(t, 'sump-01', 'state');
        // Sump chamber geometry
        var sx = 110, sy = 150, sw = 300, sh = 190, bottom = sy + sh;
        var wh = sh * fill / 100;
        var levelY = function (pct) { return bottom - sh * pct / 100; };
        var waterColor = state === 'alarm' ? C.alarm : C.water;
        var pumpX = [500, 580], pumpY = 318;

        var pumps = PUMPS.map(function (p, i) {
          var running = fresh && v(t, p.id, 'state') === 'running';
          var cx = pumpX[i];
          return h('g', {key: p.id},
            h('circle', {cx: cx, cy: pumpY, r: 22, fill: running ? C.run : C.stop, stroke: '#222', strokeWidth: 2}),
            h('g', null,
              h('line', {x1: cx - 13, y1: pumpY, x2: cx + 13, y2: pumpY, stroke: '#fff', strokeWidth: 3}),
              h('line', {x1: cx, y1: pumpY - 13, x2: cx, y2: pumpY + 13, stroke: '#fff', strokeWidth: 3}),
              running ? h('animateTransform', {attributeName: 'transform', type: 'rotate',
                from: '0 ' + cx + ' ' + pumpY, to: '360 ' + cx + ' ' + pumpY, dur: '1s', repeatCount: 'indefinite'}) : null),
            h('text', {x: cx, y: pumpY + 40, textAnchor: 'middle', fontSize: 13, fill: 'currentColor', fontWeight: 600}, p.label),
            h('text', {x: cx, y: pumpY + 54, textAnchor: 'middle', fontSize: 11, fill: 'currentColor', opacity: 0.8},
              running ? num(v(t, p.id, 'flow')) + ' м³/ч' : 'стоит'),
            h('text', {x: cx, y: pumpY + 68, textAnchor: 'middle', fontSize: 11, fill: 'currentColor', opacity: 0.8},
              running ? num(v(t, p.id, 'power')) + ' кВт' : ''));
        });
        var anyRunning = fresh && outflow > 0;
        var children = [
          // Rock, surface, shaft, horizon gallery
          h('rect', {key: 'rock', x: 0, y: 36, width: 820, height: 384, fill: C.rock}),
          h('line', {key: 'surf', x1: 0, y1: 36, x2: 820, y2: 36, stroke: '#9a8a70', strokeWidth: 3}),
          h('text', {key: 'surft', x: 10, y: 26, fontSize: 13, fill: 'currentColor', opacity: 0.8}, 'Поверхность'),
          h('rect', {key: 'shaft', x: 650, y: 36, width: 56, height: 330, fill: C.void, stroke: '#666'}),
          h('text', {key: 'shaftt', x: 664, y: 120, fontSize: 12, fill: 'currentColor', opacity: 0.8, textAnchor: 'middle',
            transform: 'rotate(-90 664 120)'}, 'Ствол'),
          h('rect', {key: 'gal', x: 430, y: 270, width: 220, height: 96, fill: C.void}),
          h('text', {key: 'galt', x: 440, y: 410, fontSize: 13, fill: 'currentColor', fontWeight: 600}, 'Горизонт 420 м · насосная камера'),
          // Inflow
          h('g', {key: 'in'}, flowLine('M 10 190 L ' + sx + ' 190', fresh && inflow > 0, 6, C.water)),
          h('text', {key: 'int', x: 10, y: 176, fontSize: 13, fill: 'currentColor'}, 'Приток ' + (fresh ? num(inflow) : '—') + ' м³/ч'),
          // Sump
          h('rect', {key: 'sump', x: sx, y: sy, width: sw, height: sh, fill: C.void, stroke: '#888', strokeWidth: 2}),
          h('rect', {key: 'water', x: sx + 2, y: bottom - wh, width: sw - 4, height: Math.max(0, wh - 1), fill: waterColor, opacity: 0.85}),
          h('line', {key: 'warn', x1: sx, y1: levelY(warnPct), x2: sx + sw, y2: levelY(warnPct), stroke: C.warn, strokeWidth: 2, strokeDasharray: '6 5'}),
          h('text', {key: 'warnt', x: sx + sw + 6, y: levelY(warnPct) + 4, fontSize: 11, fill: C.warn}, warnPct + '%'),
          h('line', {key: 'alarm', x1: sx, y1: levelY(alarmPct), x2: sx + sw, y2: levelY(alarmPct), stroke: C.alarm, strokeWidth: 2, strokeDasharray: '6 5'}),
          h('text', {key: 'alarmt', x: sx + sw + 6, y: levelY(alarmPct) + 4, fontSize: 11, fill: C.alarm}, 'авария ' + alarmPct + '%'),
          h('text', {key: 'sumpt', x: sx + sw / 2, y: sy - 10, textAnchor: 'middle', fontSize: 13, fontWeight: 600, fill: 'currentColor'}, 'Главный водосборник'),
          h('text', {key: 'vol', x: sx + sw / 2, y: bottom - 14, textAnchor: 'middle', fontSize: 18, fontWeight: 700, fill: '#fff',
            stroke: 'rgba(0,0,0,0.6)', strokeWidth: 3, paintOrder: 'stroke'},
            fresh ? num(v(t, 'sump-01', 'volume')) + ' м³ · ' + num(fill, 1) + '%' : 'нет данных'),
          // Suction from the sump to the pumps, discharge up the riser to the surface
          h('g', {key: 'suc'}, flowLine('M ' + (sx + sw) + ' 330 L ' + (pumpX[1] + 22) + ' 330', anyRunning, 5, C.water)),
          h('g', {key: 'dis1'}, flowLine('M ' + pumpX[0] + ' ' + (pumpY - 22) + ' L ' + pumpX[0] + ' 280 L 678 280', anyRunning, 5, C.water)),
          h('g', {key: 'dis2'}, flowLine('M ' + pumpX[1] + ' ' + (pumpY - 22) + ' L ' + pumpX[1] + ' 280', anyRunning, 5, C.water)),
          h('g', {key: 'riser'}, flowLine('M 678 280 L 678 22 L 800 22', anyRunning, 6, C.water)),
          h('text', {key: 'outt', x: 712, y: 14, fontSize: 12, fill: 'currentColor'}, '↑ ' + (fresh ? num(outflow) : '—') + ' м³/ч'),
          h('text', {key: 'head', x: 712, y: 160, fontSize: 11, fill: 'currentColor', opacity: 0.75}, 'став, напор 480 м')
        ];
        return h('svg', {viewBox: '0 0 820 420', role: 'img', 'aria-label': 'Схема водоотлива горизонта 420 м',
          style: {width: '100%', height: 'auto', maxHeight: props.maxHeight, display: 'block'}}, children.concat(pumps));
      }

      function Panel(props) {
        var s1 = React.useState(null), twins = s1[0], setTwins = s1[1];
        var s2 = React.useState(''), error = s2[0], setError = s2[1];
        var s3 = React.useState(''), notice = s3[0], setNotice = s3[1];
        var s4 = React.useState(''), draft = s4[0], setDraft = s4[1];
        var s5 = React.useState(null), pending = s5[0], setPending = s5[1];
        var s6 = React.useState(Date.now()), now = s6[0], setNow = s6[1];
        var pendingRef = React.useRef(null);
        var initialized = React.useRef(false);

        React.useEffect(function () {
          var active = true, timer;
          var ids = IDS.map(function (id) { return encodeURIComponent(NS + id); }).join(',');
          async function poll() {
            try {
              var list = await request('GET', '?ids=' + ids);
              if (!active) { return; }
              var map = {};
              (list || []).forEach(function (thing) { map[thing.thingId.replace(NS, '')] = thing; });
              setTwins(map);
              setError('');
              if (!initialized.current && typeof v(map, 'sump-01', 'inflow') === 'number') {
                setDraft(String(v(map, 'sump-01', 'inflow')));
                initialized.current = true;
              }
              var current = pendingRef.current;
              if (current && current.done(map)) {
                setNotice('Расчёт подтвердил: ' + current.label);
                pendingRef.current = null;
                setPending(null);
              }
            } catch (e) {
              if (active) { setError(errorText(e)); }
            }
            if (active) { timer = setTimeout(poll, 1000); }
          }
          poll();
          var clock = setInterval(function () {
            if (!active) { return; }
            setNow(Date.now());
            if (pendingRef.current && Date.now() - pendingRef.current.started > 15000) {
              setNotice('Нет подтверждения за 15 секунд: проверьте, запущен ли расчёт (drainage-simulator).');
              pendingRef.current = null;
              setPending(null);
            }
          }, 1000);
          return function () { active = false; clearTimeout(timer); clearInterval(clock); };
        }, []);

        var updated = v(twins, 'sump-01', 'updated_at');
        var age = typeof updated === 'number' ? now / 1000 - updated : Infinity;
        var fresh = !error && age > -5 && age < 15;
        var busy = !fresh || !!pending;
        var normalInflow = attr(twins, 'sump-01', 'normal_inflow_m3h') || 400;
        var maxInflow = attr(twins, 'sump-01', 'max_inflow_m3h') || 5000;

        // writes: [{id, props}] -> PUT features/control/properties of each twin
        async function send(label, writes, done) {
          if (busy || pendingRef.current) { return; }
          var command = {label: label, done: done, started: Date.now()};
          pendingRef.current = command;
          setPending(command);
          setNotice('Команда отправлена: ' + label + '. Ждём расчёт…');
          try {
            for (var i = 0; i < writes.length; i++) {
              var w = writes[i];
              var props = Object.assign({}, (twins[w.id].features.control || {}).properties || {}, w.props);
              await request('PUT', '/' + encodeURIComponent(NS + w.id) + '/features/control/properties', props);
            }
          } catch (e) {
            if (pendingRef.current === command) {
              pendingRef.current = null;
              setPending(null);
              setNotice('Команда не отправлена: ' + errorText(e));
            }
          }
        }
        function setPump(id, on, label) {
          send(label || ((on ? 'включить ' : 'отключить ') + id), [{id: id, props: {enabled: on}}],
            function (m) { return v(m, id, 'state') === (on ? 'running' : 'stopped'); });
        }
        function setInflow(amount, label) {
          send(label || ('приток ' + amount + ' м³/ч'), [{id: 'sump-01', props: {inflow_m3h: amount}}],
            function (m) { return Math.abs(v(m, 'sump-01', 'inflow') - amount) < 0.11; });
        }
        function applyInflow(event) {
          event.preventDefault();
          var text = draft.trim().replace(',', '.');
          var amount = Number(text);
          if (!text || !isFinite(amount) || amount < 0 || amount > maxInflow) {
            setNotice('Введите приток от 0 до ' + num(maxInflow) + ' м³/ч');
            return;
          }
          setInflow(amount);
        }
        var scenarios = [
          {name: 'Отказ насоса Н-1', hint: 'Н-1 останавливается, работает один Н-2',
            run: function () { setPump('pump-01', false, 'сценарий «Отказ насоса Н-1»'); }},
          {name: 'Паводок: приток ×2', hint: 'приток ' + num(normalInflow * 2) + ' м³/ч',
            run: function () { setDraft(String(normalInflow * 2)); setInflow(normalInflow * 2, 'сценарий «Паводок»'); }},
          {name: 'Обесточивание', hint: 'оба насоса останавливаются',
            run: function () {
              send('сценарий «Обесточивание»', [{id: 'pump-01', props: {enabled: false}}, {id: 'pump-02', props: {enabled: false}}],
                function (m) { return v(m, 'pump-01', 'state') === 'stopped' && v(m, 'pump-02', 'state') === 'stopped'; });
            }},
          {name: 'Вернуть норму', hint: 'оба насоса, приток ' + num(normalInflow) + ' м³/ч', reset: true,
            run: function () {
              setDraft(String(normalInflow));
              send('возврат к норме', [{id: 'pump-01', props: {enabled: true}}, {id: 'pump-02', props: {enabled: true}},
                {id: 'sump-01', props: {inflow_m3h: normalInflow}}],
                function (m) { return v(m, 'pump-01', 'state') === 'running' && v(m, 'pump-02', 'state') === 'running' && Math.abs(v(m, 'sump-01', 'inflow') - normalInflow) < 0.11; });
            }}
        ];

        // Styles
        var card = {border: '1px solid rgba(128,128,128,.35)', borderRadius: 10, padding: 14, minWidth: 0};
        var label = {fontSize: 12, opacity: 0.7, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.4};
        var btn = function (primary) {
          return {padding: '7px 12px', borderRadius: 6, border: '1px solid #498d9a', background: primary ? '#216575' : 'transparent',
            color: primary ? 'white' : 'inherit', cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.45 : 1, fontSize: 13};
        };

        var tta = v(twins, 'sump-01', 'time_to_alarm');
        var ttaText, ttaColor;
        if (!fresh) { ttaText = '—'; ttaColor = 'inherit'; }
        else if (tta === 0) { ttaText = 'АВАРИЙНЫЙ УРОВЕНЬ'; ttaColor = C.alarm; }
        else if (typeof tta === 'number' && tta < 0) { ttaText = 'вода не прибывает'; ttaColor = C.run; }
        else { ttaText = hoursText(tta); ttaColor = tta < 2 ? C.alarm : C.warn; }
        var balance = (v(twins, 'sump-01', 'inflow') || 0) - (v(twins, 'sump-01', 'outflow') || 0);
        var power = PUMPS.reduce(function (sum, p) { return sum + (v(twins, p.id, 'power') || 0); }, 0);

        function kpi(name, value, color, small) {
          return h('div', {style: Object.assign({}, card, {flex: '1 1 150px'}), key: name},
            h('div', {style: label}, name),
            h('div', {style: {fontSize: small ? 18 : 24, fontWeight: 700, color: color || 'inherit'}}, value));
        }

        var header = h('div', {style: {display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 8}},
          h('div', null,
            h('div', {style: {fontSize: 20, fontWeight: 600}}, 'Главный водоотлив · рудник «Кварцитовые Горки»'),
            h('div', {style: {fontSize: 12, opacity: 0.7}}, 'Горизонт 420 м · насосы ЦНС 300×480 · модельное время ' +
              (fresh ? num(v(twins, 'sump-01', 'sim_hours'), 1) + ' ч' : '—'))),
          h('div', {role: 'status', style: {color: fresh ? C.run : C.warn, fontSize: 13}},
            fresh ? '● Двойник на связи' : (error ? '○ ' + error : '○ Нет свежих данных от расчёта')));

        var kpis = h('div', {style: {display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10}},
          kpi('До аварийного уровня', ttaText, ttaColor),
          kpi('Баланс воды', fresh ? (balance > 0 ? '+' : '') + num(balance) + ' м³/ч' : '—', balance > 0 ? C.warn : C.run),
          kpi('Уровень в водосборнике', fresh ? num(v(twins, 'sump-01', 'level'), 2) + ' м' : '—'),
          kpi('Мощность насосов', fresh ? num(power) + ' кВт' : '—'));

        var pumpCards = PUMPS.map(function (p) {
          var running = v(twins, p.id, 'state') === 'running';
          return h('div', {key: p.id, style: Object.assign({}, card, {flex: '1 1 170px'})},
            h('div', {style: label}, 'Насос ' + p.label),
            h('div', {style: {fontSize: 17, marginBottom: 10, color: fresh && running ? C.run : 'inherit'}},
              fresh ? (running ? '● Работает' : '○ Отключён') : '—'),
            h('div', {style: {display: 'flex', gap: 6, flexWrap: 'wrap'}},
              h('button', {type: 'button', style: btn(true), disabled: busy || running, onClick: function () { setPump(p.id, true); }}, 'Включить'),
              h('button', {type: 'button', style: btn(false), disabled: busy || !running, onClick: function () { setPump(p.id, false); }}, 'Отключить')));
        });

        var inflowForm = h('form', {onSubmit: applyInflow, style: Object.assign({}, card, {flex: '1 1 220px'})},
          h('label', {htmlFor: 'inflow-' + props.id, style: label}, 'Приток воды, м³/ч'),
          h('div', {style: {display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap'}},
            h('input', {id: 'inflow-' + props.id, type: 'text', inputMode: 'decimal', value: draft, disabled: busy,
              onChange: function (e) { setDraft(e.target.value); },
              style: {padding: 7, width: 90, border: '1px solid #888', borderRadius: 6, background: 'transparent', color: 'inherit'}}),
            h('button', {type: 'submit', style: btn(true), disabled: busy}, 'Применить')),
          h('div', {style: {fontSize: 12, opacity: 0.7, marginTop: 6}}, 'Нормальный приток: ' + num(normalInflow) + ' м³/ч'));

        var scenarioCard = h('div', {style: Object.assign({}, card, {flex: '2 1 360px'})},
          h('div', {style: label}, 'Сценарии «что если»'),
          h('div', {style: {display: 'flex', gap: 6, flexWrap: 'wrap'}},
            scenarios.map(function (sc) {
              return h('button', {key: sc.name, type: 'button', title: sc.hint, disabled: busy, onClick: sc.run,
                style: btn(!sc.reset)}, sc.name);
            })),
          h('div', {style: {fontSize: 12, opacity: 0.7, marginTop: 6}}, 'Наведите на кнопку, чтобы увидеть, что она меняет. «Вернуть норму» отменяет любой сценарий.'));

        return h('div', {style: {height: props.height, overflow: 'auto', padding: 8, boxSizing: 'border-box'}},
          header,
          h(Schematic, {twins: twins, fresh: fresh, maxHeight: Math.max(260, props.height * 0.55)}),
          kpis,
          h('div', {style: {display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10}}, pumpCards, inflowForm, scenarioCard),
          h('div', {role: 'status', 'aria-live': 'polite', style: {padding: '10px 2px 0', minHeight: 28, fontSize: 13}},
            notice || 'Кнопки меняют двойников в OpenEgiz; расчёт читает их и пересчитывает водосборник. Время до аварии — в модельных часах.'));
      }
      exports('plugin', new PanelPlugin(Panel));
    }
  };
});
