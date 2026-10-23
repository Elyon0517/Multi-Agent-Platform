export interface Walkable { width: number; height: number; isWalkable(x: number, y: number): boolean; }
interface Point { x: number; y: number; }

// A* uses integer cell indices; returned steps exclude the starting cell.
export function findPath(grid: Walkable, from: Point, to: Point): Point[] | null {
  const inside = (p: Point) => Number.isInteger(p.x) && Number.isInteger(p.y) &&
    p.x >= 0 && p.y >= 0 && p.x < grid.width && p.y < grid.height;
  if (!inside(from) || !inside(to)) return null;
  if (from.x === to.x && from.y === to.y) return [];
  if (!grid.isWalkable(to.x, to.y)) return null;
  const id = ({ x, y }: Point) => y * grid.width + x;
  const point = (n: number): Point => ({ x: n % grid.width, y: Math.floor(n / grid.width) });
  const estimate = (n: number) => {
    const p = point(n); return Math.abs(p.x - to.x) + Math.abs(p.y - to.y);
  };
  const origin = id(from), destination = id(to);
  const costs = new Map([[origin, 0]]), previous = new Map<number, number>();
  const frontier = new Set([origin]);
  while (frontier.size) {
    let chosen = -1, best = Infinity;
    for (const n of frontier) {
      const rank = costs.get(n)! + estimate(n);
      if (rank < best) { chosen = n; best = rank; }
    }
    if (chosen === destination) {
      const result: Point[] = [];
      for (let n = chosen; n !== origin; n = previous.get(n)!) result.push(point(n));
      return result.reverse();
    }
    frontier.delete(chosen);
    const p = point(chosen);
    for (const q of [{ x: p.x + 1, y: p.y }, { x: p.x, y: p.y + 1 },
      { x: p.x - 1, y: p.y }, { x: p.x, y: p.y - 1 }]) {
      if (!inside(q) || !grid.isWalkable(q.x, q.y)) continue;
      const next = id(q), distance = costs.get(chosen)! + 1;
      if (distance >= (costs.get(next) ?? Infinity)) continue;
      costs.set(next, distance); previous.set(next, chosen); frontier.add(next);
    }
  }
  return null;
}
