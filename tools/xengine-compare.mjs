// Cross-engine parity probe: RTLens evidence (lexer-based Python index) vs the
// hw-topo builtin scanner (tolerant regex), run over the SAME RTL tree.
//
// This is the executable form of docs/CROSS_ENGINE_PARITY.md. It deliberately
// separates two very different questions, because conflating them is exactly how
// the two plugins became "incompatible" in the first place:
//
//   (A) COORDINATE AGREEMENT — for a fact BOTH engines report, do they agree on
//       file + line? Disagreement here is a CONTRACT VIOLATION (contract §0/R1)
//       and must be zero. This is what broke the two plugins.
//   (B) COVERAGE DIFFERENCE — facts only one engine reports (`` `ifdef`` dead
//       branches, generate loops, arrayed instances). Both engines document
//       their limits, so a difference is expected — but each one must be
//       classifiable, and it must never be silent.
//
// usage:
//   node xengine-compare.mjs <rtlRoot> <evidence.json> [--scan-rtl <path to scan-rtl.mjs>]
//
// --scan-rtl defaults to $HW_TOPO_SCAN_RTL, then to a path derived from
// $HW_TOPO_HOME (the hw-topo-dsh package root). No network, no deps.

import fs from 'node:fs';
import path from 'node:path';

function resolveScanRtl(argv) {
  const i = argv.indexOf('--scan-rtl');
  if (i !== -1 && argv[i + 1]) return argv[i + 1];
  if (process.env.HW_TOPO_SCAN_RTL) return process.env.HW_TOPO_SCAN_RTL;
  if (process.env.HW_TOPO_HOME) {
    return path.join(process.env.HW_TOPO_HOME, 'skills', 'hw-topo', 'lib', 'scan-rtl.mjs');
  }
  throw new Error(
    'cannot locate scan-rtl.mjs: pass --scan-rtl <path>, or set HW_TOPO_SCAN_RTL / HW_TOPO_HOME',
  );
}

const argv = process.argv.slice(2);

async function main() {
  const scanRtlPath = resolveScanRtl(argv);
  const positional = argv.filter((a, idx) => a !== '--scan-rtl' && argv[idx - 1] !== '--scan-rtl');
  const [repoArg, evFile] = positional;
  if (!repoArg || !evFile) {
    process.stderr.write('usage: node xengine-compare.mjs <rtlRoot> <evidence.json> [--scan-rtl <path>]\n');
    process.exit(2);
  }

  const { scanRtl } = await import(new URL(`file://${path.resolve(scanRtlPath).replace(/\\/g, '/')}`).href);

  const repo = path.resolve(repoArg);
  const ev = JSON.parse(fs.readFileSync(evFile, 'utf8'));
  if (ev.schema !== 'rtlens.evidence/1') {
    process.stderr.write(`unexpected evidence schema: ${ev.schema} (expected rtlens.evidence/1)\n`);
    process.exit(2);
  }
  const builtin = scanRtl(repo);

  // ---- rtlens side: contract uses line1 (1-based) for cross-tool evidence ----
  const rModules = ev.modules.map((m) => ({ name: m.name, file: m.file, line: m.line1, end: m.endLine1 }));
  const rInstances = ev.instances.map((i) => ({
    parent: i.parent, type: i.type, inst: i.instance, file: i.file, line: i.line1,
  }));

  // ---- builtin side ----
  const bModules = builtin.modules.map((m) => ({ name: m.name, file: m.file, line: m.line, end: m.endLine }));
  const bInstances = builtin.instantiations.map((i) => ({
    parent: i.parent, type: i.type, inst: i.instance, file: i.file, line: i.line,
  }));

  const ident = (o) => `${o.name ?? `${o.parent}>${o.type}.${o.inst}`}|${o.file}`;
  const full = (o) => `${ident(o)}|${o.line}`;

  console.log(`=== cross-engine probe: ${path.basename(repo)} ===`);
  console.log(`rtlens  : ${ev.schema} · tool=${ev.tool.name} v${ev.tool.version} · defines=${JSON.stringify(ev.defines)}`);
  console.log(`stats rtlens =${JSON.stringify(ev.stats)}`);
  console.log(`stats builtin=${JSON.stringify(builtin.stats)}`);

  let violations = 0;
  for (const [label, a, b] of [['MODULES', rModules, bModules], ['INSTANCES', rInstances, bInstances]]) {
    const count = (list, kf) => {
      const m = new Map();
      for (const it of list) m.set(kf(it), (m.get(kf(it)) ?? 0) + 1);
      return m;
    };
    const fa = count(a, full);
    const fb = count(b, full);
    let identical = 0;
    const onlyA = [];
    const onlyB = [];
    for (const [k, n] of fa) {
      const o = fb.get(k) ?? 0;
      identical += Math.min(n, o);
      if (n > o) onlyA.push(k);
    }
    for (const [k, n] of fb) if (n > (fa.get(k) ?? 0)) onlyB.push(k);

    const group = (list) => {
      const m = new Map();
      for (const it of list) {
        const k = ident(it);
        if (!m.has(k)) m.set(k, new Set());
        m.get(k).add(it.line);
      }
      return m;
    };
    const ga = group(a);
    const gb = group(b);
    const shared = [...ga.keys()].filter((k) => gb.has(k));

    // A coordinate violation means: both engines report this identity, but they
    // never agree on a single line — i.e. one of them is pointing somewhere the
    // other never points. Off-by-one shows up exactly like this ({139,151} vs
    // {140,152}).
    // Partial overlap is a COVERAGE difference, not a violation: both engines
    // point at the same real line, one of them found extra sites (generate
    // loops, dead `` `ifdef`` branches, arrayed instances).
    const disjoint = [];
    const partial = [];
    for (const k of shared) {
      const la = [...ga.get(k)].sort((x, y) => x - y);
      const lb = [...gb.get(k)].sort((x, y) => x - y);
      const common = la.filter((l) => lb.includes(l));
      if (common.length === 0) disjoint.push(`${k}\n       rtlens =[${la.join(',')}]\n       builtin=[${lb.join(',')}]`);
      else if (la.length !== lb.length) partial.push(`${k}  common=[${common.join(',')}] extra rtlens=${la.length - common.length} extra builtin=${lb.length - common.length}`);
    }
    violations += disjoint.length;

    console.log(`\n--- ${label} ---`);
    console.log(`  rtlens=${a.length}  builtin=${b.length}  identical(full key incl. line)=${identical}`);
    console.log(`  only-rtlens=${onlyA.length}  only-builtin=${onlyB.length}`);
    console.log(`  COORDINATE CHECK: shared identities=${shared.length}  VIOLATIONS=${disjoint.length}  partial-overlap(coverage)=${partial.length}`);
    if (disjoint.length) {
      console.log('  !! COORDINATE VIOLATIONS (engines never agree on a line for these):');
      for (const d of disjoint.slice(0, 10)) console.log(`     ${d}`);
    }
    if (partial.length) {
      console.log('  .. coverage differences on a shared identity (expected, must be classifiable):');
      for (const p of partial.slice(0, 5)) console.log(`     ${p}`);
    }
    if (onlyA.length) console.log(`  only-rtlens sample : ${onlyA.slice(0, 5).join(' ; ')}`);
    if (onlyB.length) console.log(`  only-builtin sample: ${onlyB.slice(0, 5).join(' ; ')}`);
  }

  const su = new Set(ev.unresolved.map((u) => u.type));
  const bu = new Set(builtin.unresolved.map((u) => u.type));
  console.log('\n--- UNRESOLVED types ---');
  console.log(`  rtlens=${su.size} builtin=${bu.size} shared=${[...su].filter((t) => bu.has(t)).length}`);
  console.log(`  only-rtlens =${[...su].filter((t) => !bu.has(t)).slice(0, 10).join(', ')}`);
  console.log(`  only-builtin=${[...bu].filter((t) => !su.has(t)).slice(0, 10).join(', ')}`);

  console.log(`\nCOORDINATE VIOLATIONS: ${violations}  (must be 0 for the contract to hold)`);
  process.exit(violations > 0 ? 1 : 0);
}

main().catch((error) => {
  process.stderr.write(`xengine-compare: ${error.message}\n`);
  process.exit(2);
});
