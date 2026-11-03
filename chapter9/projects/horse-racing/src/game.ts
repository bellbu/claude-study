export type Horse = { id:number; name:string; title:string; color:string; skill:string; ability:number; speed:number; stamina:number; odds:number };
export type RaceResult = { order:number[]; comeback:boolean; duration:number; skillTriggers:number[] };
export const INITIAL_CREDITS = 1200;
export const ROSTER = [
  ['실버 애로우','얼음 질주','#dce6f0','빙하 돌파'], ['밤의 제왕','미드나잇','#5947a8','그림자 스퍼트'], ['황금 발굽','태양의 아이','#e4b23c','골든 러시'], ['붉은 번개','폭풍의 심장','#d84c4c','번개 질주'], ['민트 스프린트','초록 돌풍','#35b99a','바람 타기'], ['코스믹 러너','별빛을 타고','#e86eae','별의 가호'], ['블루 노바','푸른 혜성','#4c8ee8','초신성 대시'], ['모래시계','마지막 1초','#c87943','시간 역행']
] as const;
const clamp=(n:number,min:number,max:number)=>Math.max(min,Math.min(max,n));
export function createField(round:number,count=5,random:()=>number=Math.random):Horse[]{
 return ROSTER.slice(0,clamp(count,4,8)).map((r,id)=>{const drift=(random()-.5)*20; const ability=Math.round(clamp(72+drift+Math.sin((round+id*2)*1.7)*9,55,96)); return {id,name:r[0],title:r[1],color:r[2],skill:r[3],ability,speed:Math.round(ability*.64+random()*18),stamina:Math.round(ability*.55+random()*32),odds:Number(clamp(1.5+((100-ability)/20)+(random()-.5)*.5,1.4,12).toFixed(1))};});
}
export function simulateRace(field:Horse[],random:()=>number=Math.random,duration=8+random()*7):RaceResult{
 const base=field.map(h=>h.ability+(random()-.5)*23+(h.speed-60)*.15+(h.stamina-60)*.08);
 const initial=[...base].map((v)=>v+(random()-.5)*3).sort((a,b)=>b-a);
 const lastIndex=base.indexOf(Math.min(...base));
 const rank=initial.length-1;
 // Target comeback frequency: 15% of races, conditional boost is confined to the current last-place runner.
 const comeback=random()<.15;
 const skills:number[]=[];
 const scores=base.map((v,id)=>{const behind=(rank===0?0:Math.max(0,(Math.max(...base)-v)/(Math.max(...base)-Math.min(...base)||1)));const chance=.06+behind*.48; if(random()<chance){skills.push(id);v+=8+behind*6;} return v+(id===lastIndex&&comeback?50:0)+(random()-.5)*12;});
 const order=scores.map((score,id)=>({score,id})).sort((a,b)=>b.score-a.score).map(x=>x.id);
 return {order,comeback:order[0]===lastIndex&&comeback,duration,skillTriggers:skills};
}
export function settle(balance:number,bet:number,odds:number,won:boolean){return Math.round(balance-bet+(won?bet*odds:0));}
export function replenish(balance:number,amount=INITIAL_CREDITS){return balance<10?amount:balance;}
export function safeLoad<T>(key:string,fallback:T):T{try{const raw=localStorage.getItem(key);return raw===null?fallback:JSON.parse(raw) as T}catch{return fallback}}


