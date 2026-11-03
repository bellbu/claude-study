import { describe,it,expect } from 'vitest';
import {createField,simulateRace,settle,replenish,INITIAL_CREDITS} from '../src/game';
describe('race game logic',()=>{
 it('generates 4 to 8 runners and odds from current ability',()=>{for(let n=4;n<=8;n++){const f=createField(1,n,()=>.5);expect(f).toHaveLength(n);expect(f.every(h=>h.odds>=1.4&&h.odds<=12)).toBe(true)}});
 it('produces a complete ordered finish with 8-15 second duration',()=>{const f=createField(2,5,()=>.4);const r=simulateRace(f,()=>.4,12);expect([...r.order].sort()).toEqual([0,1,2,3,4]);expect(r.duration).toBe(12)});
 it('settles a win and loss correctly',()=>{expect(settle(1000,100,2.5,true)).toBe(1150);expect(settle(1000,100,2.5,false)).toBe(900)});
 it('replenishes when the balance is below the minimum stake',()=>{expect(replenish(0)).toBe(INITIAL_CREDITS);expect(replenish(9)).toBe(INITIAL_CREDITS);expect(replenish(10)).toBe(10)});
 it('keeps comeback wins inside the requested 10-20% target',()=>{let comebacks=0,seed=1;const rnd=()=>{seed=(seed*16807)%2147483647;return seed/2147483647};for(let i=0;i<5000;i++){const f=createField(i,5,rnd);if(simulateRace(f,rnd).comeback)comebacks++}const rate=comebacks/5000;expect(rate).toBeGreaterThan(.1);expect(rate).toBeLessThan(.2)});
});
