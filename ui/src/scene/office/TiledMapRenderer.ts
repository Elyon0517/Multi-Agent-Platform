import { Container, Sprite, Texture, Rectangle, Matrix } from 'pixi.js';

export interface TiledMap {
  width: number;
  height: number;
  tilewidth: number;
  tileheight: number;
  layers: TiledLayer[];
  tilesets: TiledTilesetRef[];
}

export interface TiledLayer {
  name: string;
  type: 'tilelayer' | 'objectgroup';
  data?: number[];
  objects?: TiledObject[];
}

export interface TiledObject {
  name: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
}

export interface TiledTilesetRef {
  firstgid: number;
  source?: string;
  image?: string;
  columns?: number;
  tilewidth?: number;
  tileheight?: number;
  tilecount?: number;
}

export interface ZoneRect { x: number; y: number; width: number; height: number; }
export interface Point { x: number; y: number; }


// The map is indexed once. Rendering and navigation then share this immutable index.
export class TiledMapRenderer {
  readonly width: number;
  readonly height: number;
  readonly tileSize: number;
  private readonly stage = new Container();
  private readonly actors = new Container();
  private readonly blocked: Uint8Array;
  private readonly points = new Map<string, Point>();
  private readonly regions = new Map<string, ZoneRect>();
  private readonly layers = new Map<string, TiledLayer>();
  private readonly atlases: { definition: TiledTilesetRef; texture: Texture }[];

  constructor(private readonly data: TiledMap, textures: Texture[]) {
    this.width = data.width; this.height = data.height; this.tileSize = data.tilewidth;
    this.blocked = new Uint8Array(this.width * this.height);
    this.atlases = data.tilesets.map((definition, index) => ({ definition, texture: textures[index] }))
      .sort((a, b) => b.definition.firstgid - a.definition.firstgid);
    for (const layer of data.layers) this.layers.set(layer.name, layer);
    this.layers.get('collision')?.data?.forEach((gid, index) => { this.blocked[index] = gid ? 1 : 0; });
    for (const object of this.layers.get('spawn-points')?.objects ?? []) {
      const tile = this.pixelToTile(object.x, object.y);
      this.points.set(object.name, tile);
      if (/^(desk-|pc-|warroom-|entrance)/.test(object.name) && this.inBounds(tile.x, tile.y))
        this.blocked[tile.y * this.width + tile.x] = 0;
    }
    for (const object of this.layers.get('zones')?.objects ?? []) {
      this.regions.set(object.name, { ...this.pixelToTile(object.x, object.y),
        width: Math.floor((object.width ?? 0) / data.tilewidth),
        height: Math.floor((object.height ?? 0) / data.tileheight) });
    }
    for (const name of ['floor', 'walls', 'furniture-below', 'furniture-above']) {
      const group = new Container(); group.label = name;
      this.layers.get(name)?.data?.forEach((encoded, index) => {
        const texture = this.textureForGid(encoded);
        if (!texture) return;
        const sprite = new Sprite(texture);
        // Tiled flips act about the tile center, diagonal reflection first.
        const horizontal = !!(encoded & 0x80000000), vertical = !!(encoded & 0x40000000);
        const diagonal = !!(encoded & 0x20000000);
        const sx = horizontal ? -1 : 1, sy = vertical ? -1 : 1;
        const transform = diagonal ? new Matrix(0, -sy, -sx, 0) : new Matrix(sx, 0, 0, sy);
        const px = index % this.width * data.tilewidth, py = Math.floor(index / this.width) * data.tileheight;
        transform.tx = px + data.tilewidth / 2; transform.ty = py + data.tileheight / 2;
        sprite.pivot.set(data.tilewidth / 2, data.tileheight / 2);
        sprite.setFromMatrix(transform);
        group.addChild(sprite);
      });
      this.stage.addChild(group);
    }
    this.actors.sortableChildren = true; this.stage.addChild(this.actors);
  }
  private inBounds(x: number, y: number): boolean {
    return Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0 && x < this.width && y < this.height;
  }
  getContainer(): Container { return this.stage; }
  getCharacterContainer(): Container { return this.actors; }
  getSpawnPoint(name: string): Point | undefined { return this.points.get(name); }
  getAllSpawnPoints(): Map<string, Point> { return new Map(this.points); }
  getZone(name: string): ZoneRect | undefined { return this.regions.get(name); }
  getAllZones(): Map<string, ZoneRect> { return new Map(this.regions); }
  isWalkable(x: number, y: number): boolean { return this.inBounds(x, y) && !this.blocked[y * this.width + x]; }
  tileToPixel(x: number, y: number): Point { return { x: x * this.data.tilewidth, y: y * this.data.tileheight }; }
  pixelToTile(x: number, y: number): Point {
    return { x: Math.floor(x / this.data.tilewidth), y: Math.floor(y / this.data.tileheight) };
  }
  gidAt(name: string, x: number, y: number): number {
    return this.inBounds(x, y) ? (this.layers.get(name)?.data?.[y * this.width + x] ?? 0) & 0x0fffffff : 0;
  }
  textureForGid(encoded: number): Texture | undefined {
    const gid = encoded & 0x0fffffff;
    if (!gid) return;
    const atlas = this.atlases.find(({ definition }) => definition.firstgid <= gid);
    if (!atlas?.texture) return;
    const { definition: d, texture } = atlas;
    const local = gid - d.firstgid, w = d.tilewidth ?? this.data.tilewidth, h = d.tileheight ?? this.data.tileheight;
    if (local >= (d.tilecount ?? Infinity)) return;
    const columns = d.columns ?? Math.floor(texture.width / w);
    if (columns < 1) return;
    return new Texture({ source: texture.source,
      frame: new Rectangle(local % columns * w, Math.floor(local / columns) * h, w, h) });
  }
}
