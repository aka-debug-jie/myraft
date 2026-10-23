// Stable slots describe presentation only; they never choose a protocol leader.
export function geometry(ids, order, center, width, height) {
  const dense=ids.length>15, compact=!dense&&width<600, outer=order.filter(id=>id!==center), positions=new Map(), radii=new Map(), lanes=new Map();
  let w=Math.max(width,dense?1180:compact?360:680), h=Math.max(height,dense?650:620);
  const cols=dense?Math.min(5,Math.max(2,Math.ceil(Math.sqrt(outer.length/2)))):0;
  const rows=dense?Math.ceil(Math.ceil(outer.length/2)/cols):0;
  if(dense)h=Math.max(h,rows*82+180);
  const cx=w/2,cy=(h-28)/2, radius=dense?68:compact?48:60;
  if(center!=null){positions.set(center,[cx,cy]);radii.set(center,radius);}
  if(!dense){
    const rx=Math.min(w*.34,(w-132)/2),ry=Math.min((h-196)*.41,rx*(compact?1.75:1));
    outer.forEach((id,i)=>{const a=-Math.PI/2+2*Math.PI*i/Math.max(1,outer.length);positions.set(id,[cx+rx*Math.cos(a),cy+ry*Math.sin(a)]);radii.set(id,compact?(outer.length>6?26:34):outer.length>12?36:42);});
  }else{
    const half=Math.ceil(outer.length/2),pitch=Math.min(102,(w/2-190)/cols),top=cy-(rows-1)*82/2;
    outer.forEach((id,i)=>{
      const side=i<half?-1:1,k=i<half?i:i-half,row=Math.floor(k/cols),col=k%cols;
      positions.set(id,[cx+side*(190+col*pitch),top+row*82]);radii.set(id,22);
      lanes.set(id,{side,row,col,y:top+row*82-22-10-col*5});
    });
    // Independent ports around each half-circle keep all logical relationships visible.
    for(const side of [-1,1]){
      const ordered=[...lanes.values()].filter(l=>l.side===side).sort((a,b)=>a.y-b.y);
      ordered.forEach((lane,i)=>{lane.portY=radius*.94*(-1+2*i/Math.max(1,ordered.length-1));});
    }
  }
  return {positions,radii,lanes,width:w,height:h,center,cx,cy,dense,compact};
}

const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
function clip(a,b,r){const d=distance(a,b)||1;return[a[0]+(b[0]-a[0])*r/d,a[1]+(b[1]-a[1])*r/d];}
function crosses(a,b,p,r){
  // Segment against an expanded axis-aligned node box, including its boundary.
  let low=0,high=1;
  for(let axis=0;axis<2;axis++){
    const delta=b[axis]-a[axis],min=p[axis]-r,max=p[axis]+r;
    if(Math.abs(delta)<1e-8){if(a[axis]<min||a[axis]>max)return false;}
    else{let t1=(min-a[axis])/delta,t2=(max-a[axis])/delta;if(t1>t2)[t1,t2]=[t2,t1];low=Math.max(low,t1);high=Math.min(high,t2);if(low>high)return false;}
  }
  return true;
}
function clear(points,g,from,to){
  for(const [id,p] of g.positions){if(id===from||id===to)continue;const r=g.radii.get(id)+5;
    for(let i=1;i<points.length;i++)if(crosses(points[i-1],points[i],p,r))return false;
  }
  return true;
}
function simplify(points){
  const out=[];
  for(const p of points){if(out.length&&distance(out.at(-1),p)<.01)continue;
    while(out.length>=2){const a=out.at(-2),b=out.at(-1);if(Math.abs((b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0]))>.01)break;out.pop();}out.push(p);
  }return out;
}
function rounded(points,radius=4){
  if(points.length<2)return '';
  let d=`M${points[0].join(',')}`;
  for(let i=1;i<points.length-1;i++){
    const a=points[i-1],b=points[i],c=points[i+1],r=Math.min(radius,distance(a,b)/3,distance(b,c)/3);
    const before=clip(b,a,r),after=clip(b,c,r);d+=` L${before.join(',')} Q${b.join(',')} ${after.join(',')}`;
  }return d+` L${points.at(-1).join(',')}`;
}

// Rare non-central relationships use a sparse corridor graph, not a force layout.
function orthogonal(g,from,to){
  const start=g.positions.get(from),end=g.positions.get(to),xs=new Set([start[0],end[0],20,g.width-20]),ys=new Set([start[1],end[1],20,g.height-20]);
  for(const[id,p]of g.positions){const r=g.radii.get(id)+12;xs.add(p[0]-r);xs.add(p[0]+r);ys.add(p[1]-r);ys.add(p[1]+r);}
  const xx=[...xs].sort((a,b)=>a-b),yy=[...ys].sort((a,b)=>a-b),nx=xx.length;
  const first=yy.indexOf(start[1])*nx+xx.indexOf(start[0]),last=yy.indexOf(end[1])*nx+xx.indexOf(end[0]);
  const point=n=>[xx[n%nx],yy[Math.floor(n/nx)]],heap=[],cost=new Map(),previous=new Map(),allowed=new Map();
  function push(item){heap.push(item);let i=heap.length-1;while(i>0){const p=(i-1)>>1;if(heap[p][0]<=item[0])break;heap[i]=heap[p];i=p;}heap[i]=item;}
  function pop(){const result=heap[0],item=heap.pop();if(heap.length){let i=0;while(i*2+1<heap.length){let c=i*2+1;if(c+1<heap.length&&heap[c+1][0]<heap[c][0])c++;if(heap[c][0]>=item[0])break;heap[i]=heap[c];i=c;}heap[i]=item;}return result;}
  const initial=first*3;cost.set(initial,0);push([0,initial]);let finish;
  while(heap.length){
    const[,state]=pop(),node=Math.floor(state/3),dir=state%3,here=point(node);
    if(node===last){finish=state;break;}
    const x=node%nx,y=Math.floor(node/nx);
    for(const[next,axis]of [[x>0?node-1:-1,1],[x+1<nx?node+1:-1,1],[y>0?node-nx:-1,2],[y+1<yy.length?node+nx:-1,2]]){
      if(next<0)continue;const there=point(next),key=node<next?`${node}/${next}`:`${next}/${node}`;
      if(!allowed.has(key))allowed.set(key,clear([here,there],g,from,to));if(!allowed.get(key))continue;
      const ns=next*3+axis,value=cost.get(state)+distance(here,there)+(dir&&dir!==axis?16:0);
      if(value>=(cost.get(ns)??Infinity))continue;cost.set(ns,value);previous.set(ns,state);
      push([value+Math.abs(there[0]-end[0])+Math.abs(there[1]-end[1]),ns]);
    }
  }
  if(finish===undefined)return [];
  const path=[];for(let s=finish;s!==undefined;s=previous.get(s))path.push(point(Math.floor(s/3)));
  const points=simplify(path.reverse());
  if(points.length>1){points[0]=clip(start,points[1],g.radii.get(from));points[points.length-1]=clip(end,points.at(-2),g.radii.get(to));}
  return points;
}

export function route(g,from,to){
  const a=g.positions.get(from),b=g.positions.get(to);if(!a||!b)return '';
  let points;
  if(g.dense&&to===g.center&&g.lanes.has(from)){
    const lane=g.lanes.get(from),r=g.radii.get(to),dy=lane.portY,dx=lane.side*Math.sqrt(r*r-dy*dy);
    const tip=[b[0]+dx,b[1]+dy],entry=[g.cx+lane.side*150,lane.y];
    points=[[a[0],a[1]-g.radii.get(from)],[a[0],lane.y],entry];
    // Ordered fan controls avoid crossings; each relationship has its own circle port.
    return rounded(simplify(points),8)+` C${g.cx+lane.side*120},${lane.y} ${g.cx+lane.side*105},${tip[1]} ${g.cx+lane.side*(r+20)},${tip[1]} L${tip.join(',')}`;
  }
  if(!points){const direct=[clip(a,b,g.radii.get(from)),clip(b,a,g.radii.get(to))];points=clear(direct,g,from,to)?direct:orthogonal(g,from,to);}
  return rounded(simplify(points));
}

// Flatten our M/L/Q/C paths once for precise pointer picking between dense strokes.
export function pathSegments(d) {
  const tokens=d.match(/[MLQC]|[-+]?(?:\d*\.?\d+)(?:e[-+]?\d+)?/g)||[],points=[];
  let i=0,at;
  const point=()=>[Number(tokens[i++]),Number(tokens[i++])];
  const mid=(a,b)=>[(a[0]+b[0])/2,(a[1]+b[1])/2];
  function curve(a,b,c,e,depth=0){
    const deviation=p=>Math.abs((e[0]-a[0])*(a[1]-p[1])-(a[0]-p[0])*(e[1]-a[1]))/(distance(a,e)||1);
    if(depth>=12||Math.max(deviation(b),deviation(c))<.02){points.push(e);return;}
    const ab=mid(a,b),bc=mid(b,c),ce=mid(c,e),left=mid(ab,bc),right=mid(bc,ce),center=mid(left,right);
    curve(a,ab,left,center,depth+1);curve(center,right,ce,e,depth+1);
  }
  while(i<tokens.length){const command=tokens[i++];
    if(command==='M'||command==='L'){at=point();points.push(at);}
    else if(command==='Q'){const b=point(),end=point();curve(at,at.map((v,j)=>v+(b[j]-v)*2/3),end.map((v,j)=>v+(b[j]-v)*2/3),end);at=end;}
    else if(command==='C'){const b=point(),c=point(),end=point();curve(at,b,c,end);at=end;}
  }
  return points.slice(1).map((p,i)=>[points[i],p]);
}
