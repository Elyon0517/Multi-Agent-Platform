/**
 * Reservation pool for a fixed ordered list of seat identifiers (the desk/pc
 * spawn points in the Tiled map). Used to hand each dynamically-added agent a
 * distinct seat. Ported verbatim from shahar061/the-office (office/SeatPool.ts).
 */
export class SeatPool {
  private readonly seats: readonly string[];
  private claimed = new Set<string>();

  constructor(seats: readonly string[]) {
    this.seats = seats;
  }

  /** Reserve the first unoccupied seat in list order, or null if all taken. */
  reserveNext(): string | null {
    for (const seat of this.seats) {
      if (!this.claimed.has(seat)) {
        this.claimed.add(seat);
        return seat;
      }
    }
    return null;
  }

  /** Release a previously-reserved seat. Idempotent. */
  release(seat: string): void {
    this.claimed.delete(seat);
  }

  isReserved(seat: string): boolean {
    return this.claimed.has(seat);
  }
}
