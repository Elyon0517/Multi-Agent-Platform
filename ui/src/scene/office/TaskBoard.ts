import { Container, Graphics } from 'pixi.js';
import type { BoardTask } from '@/store/store';
import type { Point } from './TiledMapRenderer';
export interface TaskMarker { id: string; status: string; x: number; y: number; }
// Locations are map-space pixels; unassigned work stays visible on the wall.
export function taskMarkers(tasks: Pick<BoardTask,'id'|'status'|'assignee'>[], seats: ReadonlyMap<string, Point>,
  board: Point, tileSize: number): TaskMarker[] {
  let blocked = 0, queued = 0, archived = 0;
  const deskCounts = new Map<string, number>();
  return tasks.map(task => {
    const desk = task.assignee ? seats.get(task.assignee) : undefined;
    let x: number, y: number;
    if (task.status === 'doing' && desk) {
      const index = deskCounts.get(task.assignee!) ?? 0; deskCounts.set(task.assignee!, index + 1);
      x = (desk.x - 1) * tileSize + 3 + index * 7; y = (desk.y - 1) * tileSize + 8 - index % 2;
    } else if (task.status === 'done') {
      const layer = Math.min(5, archived++); x = board.x + 71 + layer % 2; y = board.y + 4 - layer * 2;
    } else {
      const burning = task.status === 'blocked', index = burning ? blocked++ : queued++;
      x = board.x + (burning ? 3 : 37) + Math.min(11,index) % 4 * 7;
      y = board.y - 2 + Math.floor(Math.min(11,index) / 4) * 5;
    }
    return { id: task.id, status: task.status, x, y };
  });
}
export class TaskBoard {
  readonly container = new Container();
  private readonly backdrop = new Graphics();
  private readonly notes = new Map<string, { image: Graphics; x: number; y: number; age: number }>();
  constructor(private readonly origin: Point, private readonly tileSize: number,
    private readonly palette: Record<string,number>, onOpen: () => void) {
    this.backdrop.position.set(origin.x,origin.y);
    for (const [offset, color] of [[0,palette.blocked],[34,palette.todo]]) {
      this.backdrop.rect(offset,-8,30,22).fill(0x6e5639);
      this.backdrop.rect(offset+1,-7,28,3).fill(color);
      this.backdrop.rect(offset+1,-4,28,17).fill(0xc9b083);
    }
    this.backdrop.rect(68,6,14,4).fill(0xb08d5e).rect(68,10,14,4).fill(0x8a6f4d);
    this.backdrop.rect(69,14,2,2).fill(0x6e5639).rect(79,14,2,2).fill(0x6e5639);
    this.backdrop.eventMode = 'static'; this.backdrop.cursor = 'pointer';
    this.backdrop.on('pointertap', event => { event.stopPropagation(); onOpen(); });
    this.container.addChild(this.backdrop); this.container.zIndex = origin.y + tileSize;
  }
  sync(tasks: BoardTask[], seats: ReadonlyMap<string,Point>): void {
    const markers = taskMarkers(tasks,seats,this.origin,this.tileSize), wanted = new Set(markers.map(marker => marker.id));
    for (const [id,note] of this.notes) if (!wanted.has(id)) { note.image.destroy(); this.notes.delete(id); }
    for (const marker of markers) {
      const old = this.notes.get(marker.id);
      const note = old ?? { image: new Graphics(), x: marker.x, y: marker.y, age: 1 };
      if (!old) { note.image.position.set(marker.x,marker.y); this.container.addChild(note.image); this.notes.set(marker.id,note); }
      if (note.x !== marker.x || note.y !== marker.y) note.age = 0;
      note.x = marker.x; note.y = marker.y;
      note.image.clear().rect(0,0,marker.status === 'done' ? 8 : 5,marker.status === 'done' ? 2 : 4)
        .fill(this.palette[marker.status] ?? this.palette.todo);
      if (marker.status !== 'done') note.image.rect(2,0,1,1).fill(0x4a3b52);
      note.image.eventMode = 'none';
    }
  }
  update(seconds: number): void {
    for (const note of this.notes.values()) {
      note.age = Math.min(1,note.age + seconds * 2);
      const blend = Math.min(1,seconds * 10);
      note.image.x += (note.x - note.image.x) * blend;
      note.image.y += (note.y - note.image.y) * blend;
    }
  }
  destroy(): void { this.container.destroy({ children: true }); this.notes.clear(); }
}
