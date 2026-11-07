/* Needle scale helpers (pure, shared with tests). */
export const MARKS = [0, 1, 2, 5, 10, 50, 100, 250, 500, 750, 1000];
export const CX = 180;
export const CY = 170;
export const R = 140;

export function mbpsToAngle(mbps) {
  if (mbps === null || mbps === undefined || !isFinite(mbps)) return -90;
  const v = Math.max(0, Math.min(1000, Number(mbps)));
  if (v <= 0) return -90;
  return -90 + 180 * (Math.log10(v + 1) / Math.log10(1001));
}

export function polar(angleDeg, radius) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + radius * Math.sin(rad), y: CY - radius * Math.cos(rad) };
}

export function arcPath(angleDeg) {
  const end = polar(angleDeg, R);
  return `M ${polar(-90, R).x} ${polar(-90, R).y} A ${R} ${R} 0 0 1 ${end.x} ${end.y}`;
}

export function tickMarkup() {
  const stagger = new Map([[500, R - 34], [750, R - 60], [1000, R - 34]]);
  return MARKS.map((mark) => {
    const angle = mbpsToAngle(mark);
    const inner = polar(angle, R - 14);
    const outer = polar(angle, R + 2);
    const label = polar(angle, stagger.get(mark) || R - 36);
    return `<g>
      <line x1="${inner.x}" y1="${inner.y}" x2="${outer.x}" y2="${outer.y}" class="gauge-tick" />
      <text x="${label.x}" y="${label.y + 4}" class="gauge-tick-label">${mark}</text>
    </g>`;
  }).join('');
}
