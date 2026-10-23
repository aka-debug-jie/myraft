// Stable slots describe presentation only; they never choose a protocol leader.
export function geometry(ids, order, center, width, height) {
  const w=Math.max(240,width),h=Math.max(200,height),cx=w/2,cy=h/2;
  const rx=Math.max(40,w/2-40),ry=Math.max(40,h/2-104),positions=new Map(),radii=new Map(),slots=new Map();
  const points=[],lengths=[0];let length=0;
  // Equal arc lengths avoid squeezing nodes at the narrow end of an ellipse.
  for(let i=0;i<=720;i++){
    const angle=-Math.PI/2+i*Math.PI/360,p=[cx+rx*Math.cos(angle),cy+ry*Math.sin(angle)];
    if(i)length+=Math.hypot(p[0]-points[i-1][0],p[1]-points[i-1][1]);points.push(p);lengths.push(length);
  }
  let j=1;
  order.forEach((id,i)=>{const target=length*i/Math.max(1,order.length);
    while(j<points.length-1&&lengths[j+1]<target)j++;
    const lo=lengths[j],hi=lengths[j+1],t=hi>lo?(target-lo)/(hi-lo):0;
    const p=[points[j-1][0]+(points[j][0]-points[j-1][0])*t,points[j-1][1]+(points[j][1]-points[j-1][1])*t];
    if(h<400&&order.length<=2){p[0]=cx+(i?1:-1)*rx;p[1]=cy;}
    slots.set(id,p);positions.set(id,p);radii.set(id,w<600?26:order.length<=15?38:22);
  });
  const outside=order.filter(id=>id!==center);let minAngle=Math.PI;
  const angles=outside.map(id=>{const p=slots.get(id);return Math.atan2(p[1]-cy,p[0]-cx)}).sort((a,b)=>a-b);
  for(let i=0;i<angles.length;i++)minAngle=Math.min(minAngle,(angles[(i+1)%angles.length]-angles[i]+2*Math.PI)%(2*Math.PI)||2*Math.PI);
  // 6px clear space plus a 1.8px highlighted stroke at the center ports.
  const radius=Math.max(h<400?40:w<600?46:60,angles.length>1?7.8/(2*Math.sin(minAngle/2))+.5:0);
  if(center!=null){positions.set(center,[cx,cy]);radii.set(center,radius);}
  let fits=h<400&&order.length<=2?radius+10<h/2-44:radius+40<Math.min(rx,ry);
  for(const id of outside){const a=positions.get(id);
    if(center!=null&&Math.hypot(a[0]-cx,a[1]-cy)<radius+radii.get(id)+12)fits=false;
    for(const other of outside){if(other<=id)continue;const b=positions.get(other);if(Math.hypot(a[0]-b[0],a[1]-b[1])<radii.get(id)+radii.get(other)+8)fits=false;}
  }
  return {positions,radii,slots,lanes:new Map(),width:w,height:h,center,cx,cy,dense:order.length>15,compact:w<600,fits};
}

const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
function clip(a,b,r){const d=distance(a,b)||1;return[a[0]+(b[0]-a[0])*r/d,a[1]+(b[1]-a[1])*r/d];}
function crosses(a,b,p,r){
  const dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
  const t=length?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)):0;
  return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)<=r;
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
