import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Application, Assets, Graphics, Text, type Texture } from 'pixi.js';
import 'pixi.js/unsafe-eval';
import { useStore, type Agent } from '@/store/store';
import { activeFloorAgents, floorAgentLabel } from '../adapter/activity';
import { loadTheme, resolveThemeMap, themeTilesetUrls } from './themeLoader';
import { TiledMapRenderer, type Point } from './TiledMapRenderer';
import { Character } from './Character';
import { Camera } from './Camera';
import { TaskBoard } from './TaskBoard';
import { DeskScreen } from './DeskScreen';
import { MessageEnvelope, type MessageAct } from './MessageEnvelope';
import { installContextLossRecovery, planInitFailure } from './glRecovery';

interface Actor {
  character: Character; seat: number; status: string; model: string; leaving: boolean; departed?: boolean; screen?: DeskScreen;
}

export function OfficeFloor() {
  const themeId = useStore(state => state.officeTheme);
  const host = useRef<HTMLDivElement>(null);
  const attempts = useRef(0);
  const { i18n } = useTranslation();
  const [generation, rebuild] = useState(0), [error, setError] = useState('');
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let live = true, ready = false;
    const disposers: (() => void)[] = [];
    const app = new Application();
    const actors = new Map<string, Actor>(), pending = new Set<string>(), claims = new Map<number, string>();
    const deliveries: MessageEnvelope[] = [];
    const release = (id: string) => {
      const actor = actors.get(id);
      if (actor) { actor.character.destroy(); actor.screen?.destroy(); claims.delete(actor.seat); actors.delete(id); }
    };
    const disposeApp = () => {
      if (!ready) return;
      ready = false; app.ticker.stop();
      for (const id of actors.keys()) release(id);
      deliveries.forEach(delivery => delivery.destroy());
      app.destroy(true, { children: true });
    };
    const initialize = async () => {
      setError('');
      const theme = await loadTheme(themeId);
      if (!live) return;
      await app.init({ width: Math.max(1, element.clientWidth), height: Math.max(1, element.clientHeight),
        background: theme.palette.background, antialias: false, resolution: devicePixelRatio || 1, autoDensity: true });
      ready = true;
      if (!live) { disposeApp(); return; }
      element.appendChild(app.canvas);
      const textures = await Promise.all(themeTilesetUrls(theme).map(url => Assets.load<Texture>(url)));
      if (!live) return;
      const map = new TiledMapRenderer(resolveThemeMap(theme), textures);
      const world = map.getContainer(), layer = map.getCharacterContainer();
      app.stage.addChild(world);
      const camera = new Camera(world);
      camera.setMapSize(map.width * map.tileSize, map.height * map.tileSize);
      const resize = () => {
        const w = element.clientWidth, h = element.clientHeight;
        if (w > 0 && h > 0) { app.renderer.resize(w, h); camera.setViewSize(w, h); }
      };
      resize(); const observer = new ResizeObserver(resize); observer.observe(element);
      disposers.push(() => observer.disconnect());
      const entrance = map.getSpawnPoint('entrance') ?? { x: 1, y: 1 };
      const seats = theme.primarySeatNames.map(name => map.getSpawnPoint(name)).filter((p): p is Point => !!p);
      const update = (agent: Agent, actor: Actor) => {
        const character = actor.character;
        character.setName(agent.name);
        if (actor.status === agent.status && !actor.leaving) return;
        if (actor.leaving || actor.departed) character.show(layer);
        actor.status = agent.status; actor.leaving = false; actor.departed = false;
        character.setStatusGlyph(agent.status === 'compacting' ? 'compacting' :
          agent.status === 'looping' ? 'looping' : agent.status === 'blocked' ? 'blocked' :
          agent.status === 'success' ? 'success' : 'none');
        character.showThought(floorAgentLabel(agent), agent.carrying);
        if (agent.id === 'root' || ['working','thinking','compacting','waiting','looping'].includes(agent.status))
          character.sitAtDesk(['working','thinking','compacting'].includes(agent.status));
        else if (agent.status === 'blocked') character.walkToTile(entrance);
        else character.setIdle();
      };
      const spawn = async (agent: Agent) => {
        if (pending.has(agent.id)) return;
        pending.add(agent.id);
        const seat = agent.id === 'root' ? 0 : seats.findIndex((_, index) => index > 0 && !claims.has(index));
        if (seat < 0 || !seats[seat]) { pending.delete(agent.id); return; }
        claims.set(seat, agent.id);
        try {
          const frames = await theme.cast.getFrames(agent.character);
          const current = activeFloorAgents(useStore.getState().agents, useStore.getState().rootBusy).find(a => a.id === agent.id);
          if (!live || !current) { claims.delete(seat); return; }
          if (current.character !== agent.character) {
            claims.delete(seat);
            queueMicrotask(() => { if (live) void spawn(current).catch(fail); });
            return;
          }
          const character = new Character({ agentId: agent.id, displayName: current.name, frames, mapRenderer: map,
            seatTile: seats[seat], spawnTile: agent.id === 'root' ? seats[seat] : entrance,
            glowColor: theme.cast.byName[agent.character] ? Number.parseInt(theme.cast.byName[agent.character].shirt.slice(1), 16) : 0x4f9faf,
            seatDirection: 'up', onClick: id => useStore.getState().select(id) });
          character.show(layer);
          const top = { x: seats[seat].x, y: seats[seat].y - 2 };
          const screen = map.gidAt('furniture-above', top.x, top.y) === theme.monitor.offTopLeftGid
            ? new DeskScreen(map, top, theme.monitor) : undefined;
          if (screen) layer.addChild(screen.container);
          const actor: Actor = { character, seat, screen, status: '', model: agent.character, leaving: false };
          actors.set(agent.id, actor); update(current, actor); paintBoards();
        } finally { pending.delete(agent.id); }
      };
      const synchronize = () => {
        const state = useStore.getState(), roster = activeFloorAgents(state.agents, state.rootBusy);
        const wanted = new Set(roster.map(agent => agent.id));
        for (const [id, actor] of actors) if (!wanted.has(id) && !actor.leaving) {
          actor.leaving = true; actor.character.hideThought();
          actor.character.walkToAndThen(entrance, () => {
            if (actor.leaving) { actor.departed = true; actor.character.hide(); }
          });
        }
        for (const agent of roster) {
          const actor = actors.get(agent.id);
          if (actor && actor.model !== agent.character) { release(agent.id); void spawn(agent).catch(fail); }
          else if (actor) update(agent, actor);
          else void spawn(agent).catch(fail);
        }
      };
      const open = (tab: 'tasks' | 'human' | 'project') => {
        const state = useStore.getState(); const root = state.agents.find(agent => agent.isGod);
        if (root) state.select(root.id); state.requestCommandCenterTab(tab === 'human' ? 'chat' : tab);
      };
      // Interactive furniture is independent from the authored map's static atlas.
      const prop = (at: Point, draw: (graphic: Graphics) => void, action: () => void) => {
        const graphic = new Graphics(); draw(graphic); graphic.position.set(at.x * map.tileSize, at.y * map.tileSize);
        graphic.zIndex = (at.y + 2) * map.tileSize; graphic.eventMode = 'static'; graphic.cursor = 'pointer';
        graphic.on('pointertap', event => { event.stopPropagation(); action(); }); layer.addChild(graphic); return graphic;
      };
      prop(theme.anchors.calendar, g => {
        g.rect(8, 5, 16, 20).fill(0xfffdf5).stroke({ color: 0x4a3b52, width: 1 });
        g.rect(8, 5, 16, 5).fill(0xd96a62);
        for (let n = 0; n < 6; n++) g.rect(11 + n % 3 * 4, 13 + Math.floor(n / 3) * 4, 2, 2).fill(0x6b5878);
      }, () => open('project'));
      const board = new TaskBoard({ x: theme.anchors.boards.x * map.tileSize + 15, y: theme.anchors.boards.y * map.tileSize },
        map.tileSize, theme.palette.noteColors, () => open('tasks')); layer.addChild(board.container);
      const ask = prop({ x: 15.5, y: 10 }, () => undefined, () => open('human'));
      const question = new Text({ text: '?', style: { fontFamily: 'monospace', fontSize: 12, fill: 0x8a755f } });
      question.position.set(ask.x + 11, ask.y - 4); question.zIndex = ask.zIndex + 1; question.eventMode = 'none'; layer.addChild(question);
      const clock = prop(theme.anchors.clock, g => g.circle(8, 8, 7).fill(0xfffdf5).stroke({ color: 0x4a3b52, width: 1 }), () => window.close());
      const hands = new Graphics(); hands.position.copyFrom(clock.position);
      hands.zIndex = clock.zIndex + 1; hands.eventMode = 'none'; layer.addChild(hands);
      let lastTasks = useStore.getState().tasks;
      const paintBoards = () => {
        const tasks = useStore.getState().tasks;
        const seats = new Map(Array.from(actors, ([id,actor]) => [id,actor.character.getDeskTile()]));
        board.sync(tasks,seats);
        const count = tasks.filter(task => task.status === 'blocked' && task.humanQA?.some(q => !q.a && !q.dismissedAt)).length;
        question.visible = count === 0;
        ask.clear().rect(0, -8, 30, 22).fill(0x5b4a6b).rect(1, -4, 28, 17).fill(0xc9b083);
        for (let n = 0; n < Math.min(9, count); n++) ask.rect(4 + n % 3 * 8, -1 + Math.floor(n / 3) * 4, 5, 3)
          .fill(count ? 0xcdb4e8 : 0x8a755f);
        lastTasks = tasks;
      };
      paintBoards();
      const send = (from: string, to: string, act: MessageAct, human = false) => {
        if (from === to || deliveries.length >= 24) return;
        const location = (id: string) => id === 'human' ? map.tileToPixel(entrance.x, entrance.y) : actors.get(id)?.character.getPixelPosition();
        const a = location(from), b = location(to); if (!a || !b) return;
        const envelope = new MessageEnvelope(a, b, act, human); layer.addChild(envelope.container); deliveries.push(envelope);
      };
      disposers.push(useStore.subscribe((state, previous) => {
        if (state.agents !== previous.agents || state.rootBusy !== previous.rootBusy) synchronize();
        if (state.tasks !== lastTasks) paintBoards();
        if (state.selectedId !== previous.selectedId) {
          const at = state.selectedId && actors.get(state.selectedId)?.character.getPixelPosition();
          if (at) camera.nudgeToward(at.x, at.y);
        }
      }));
      disposers.push(window.cth.onHiveMessage(event => event.targets.forEach(target => send(event.from, target, event.act, event.needsHuman))));
      const demo = (event: Event) => { const d = (event as CustomEvent<{ from: string; to: string; act: MessageAct }>).detail;
        if (d) send(d.from, d.to, d.act); };
      window.addEventListener('cth:demo-handoff', demo); disposers.push(() => window.removeEventListener('cth:demo-handoff', demo));
      const pause = () => { const state = useStore.getState();
        if (document.hidden || state.ideOpen || state.fullscreenAgentId) app.ticker.stop(); else app.ticker.start(); };
      document.addEventListener('visibilitychange', pause); disposers.push(() => document.removeEventListener('visibilitychange', pause));
      disposers.push(useStore.subscribe(pause));
      disposers.push(installContextLossRecovery(app.canvas, { maxRebuilds: Math.max(0, 3 - attempts.current),
        onRebuild: () => { attempts.current++; if (live) rebuild(n => n + 1); },
        onGiveUp: () => setError('The workspace renderer lost its GPU context. Reload to try again.') }));
      app.ticker.add(ticker => {
        const seconds = Math.min(.1, ticker.deltaMS / 1000); camera.update(seconds);
        const placed: { x: number; y: number; w: number; h: number }[] = [];
        for (const actor of actors.values()) {
          actor.character.setThoughtLift(0); actor.character.setBubbleZoom(world.scale.x); actor.character.update(seconds);
          if (actor.departed && !actor.character.isVisible) { release(actor.character.agentId); paintBoards(); continue; }
          actor.screen?.setOn(actor.character.isSittingAtDesk()); actor.screen?.update(seconds);
          const box = actor.character.getThoughtLayout();
          if (box) {
            let y = box.y;
            for (const previous of placed) if (box.x < previous.x + previous.w && box.x + box.w > previous.x && y + box.h > previous.y && y < previous.y + previous.h)
              y = Math.min(y, previous.y - box.h - 2);
            actor.character.setThoughtLift(box.y - y); placed.push({ ...box, y });
          }
        }
        for (let n = deliveries.length - 1; n >= 0; n--) if (deliveries[n].update(seconds)) {
          deliveries[n].destroy(); deliveries.splice(n, 1);
        }
        board.update(seconds);
        const now = new Date(), minute = now.getMinutes() * Math.PI / 30, hour = (now.getHours() % 12 + now.getMinutes() / 60) * Math.PI / 6;
        hands.clear().moveTo(8, 8).lineTo(8 + Math.sin(minute) * 5, 8 - Math.cos(minute) * 5)
          .moveTo(8, 8).lineTo(8 + Math.sin(hour) * 3, 8 - Math.cos(hour) * 3).stroke({ color: 0x1a1320, width: 1 });
      });
      synchronize(); pause();
    };
    const fail = (failure: unknown) => {
      if (!live) return;
      const plan = planInitFailure(failure, attempts.current);
      if (plan.action === 'retry') {
        attempts.current = plan.attempt;
        const timer = setTimeout(() => { if (live) rebuild(n => n + 1); }, plan.delayMs);
        disposers.push(() => clearTimeout(timer));
      } else setError(failure instanceof Error ? failure.message : String(failure));
    };
    void initialize().catch(fail);
    return () => { live = false; disposers.reverse().forEach(stop => stop()); disposeApp(); };
  }, [themeId, generation, i18n.language]);
  return <div ref={host} style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden',
    boxShadow: 'var(--cth-panel-border)', imageRendering: 'pixelated', background: '#1a1320' }}>
    {error && <div role="alert" style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center',
      color: '#ffd0b5', padding: 24, font: '13px monospace', textAlign: 'center' }}>{error}</div>}
  </div>;
}
