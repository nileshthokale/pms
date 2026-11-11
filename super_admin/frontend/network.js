// Optional visualization only: accepts licensing records, never fetches or mutates them.
import * as THREE from './three.module.min.js';

const palette = {online:0x6cefce,offline:0x918d8d,new:0xe8be78,revoked:0xf76e99,cyan:0xffffff};
export function createNetwork(host, {onSelect,onState,onFailure,paused=false,reducedMotion=false}) {
  const renderer = new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.6)); renderer.setClearColor(0x000000,0);
  renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.35;
  const canvas=renderer.domElement;canvas.setAttribute('aria-hidden','true');host.prepend(canvas);
  const scene=new THREE.Scene();scene.fog=new THREE.FogExp2(0x000000,.022);
  const camera=new THREE.PerspectiveCamera(36,1,.1,100);camera.position.set(10,11,15);camera.lookAt(0,.3,0);
  scene.add(new THREE.AmbientLight(0xffffff,2));
  const key=new THREE.DirectionalLight(0xffffff,4);key.position.set(-4,9,4);scene.add(key);
  const rim=new THREE.PointLight(0xffffff,25,30);rim.position.set(6,5,-5);scene.add(rim);
  const glow=new THREE.PointLight(0xffffff,12,15);glow.position.set(-3,3,1);scene.add(glow);
  const stage=new THREE.Group();scene.add(stage);
  const devicesGroup=new THREE.Group();scene.add(devicesGroup);
  const labels=[],entries=[];let hitMeshes=[],records=[],signature='',selection='',visible=true,disposed=false,frame=0,lastFrame=0,phase=0;
  const pointer=new THREE.Vector2(),targetPointer=new THREE.Vector2(),raycaster=new THREE.Raycaster(),projected=new THREE.Vector3();
  const tooltip=host.querySelector('#network-tooltip');
  function metal(color,emissive=0x000000,opacity=1) {return new THREE.MeshStandardMaterial({color,metalness:.65,roughness:.3,emissive,emissiveIntensity:.35,transparent:opacity<1,opacity});}
  function mesh(geometry,material,parent,x=0,y=0,z=0) {const object=new THREE.Mesh(geometry,material);object.position.set(x,y,z);parent.add(object);return object;}
  function box(parent,w,h,d,color,x=0,y=0,z=0,emissive=0,opacity=1) {return mesh(new THREE.BoxGeometry(w,h,d),metal(color,emissive,opacity),parent,x,y,z);}
  function ring(parent,radius,y,color,opacity=.45) {const object=mesh(new THREE.TorusGeometry(radius,.018,8,96),new THREE.MeshBasicMaterial({color,transparent:true,opacity}),parent,0,y,0);object.rotation.x=-Math.PI/2;return object;}
  function label(text,position,id,cls='') {const element=document.createElement('span');element.className='network-label '+cls;element.textContent=text;if(id)element.dataset.deviceId=id;host.append(element);const record={element,position};labels.push(record);return record;}
  // Ground grid, particles, and rings describe the environment, not additional installations.
  const grid=new THREE.GridHelper(20,30,0x454242,0x272626);grid.position.y=-.15;grid.material.transparent=true;grid.material.opacity=.35;stage.add(grid);
  ring(stage,3.4,-.08,0x918d8d,.16);ring(stage,5.6,-.07,0x918d8d,.14);ring(stage,7.9,-.07,0x918d8d,.12);
  const positions=new Float32Array(90*3);for(let i=0;i<90;i++){positions[i*3]=Math.sin(i*12.989)*9;positions[i*3+1]=.2+(i%11)*.28;positions[i*3+2]=Math.cos(i*7.137)*8;}
  const particles= new THREE.Points(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(positions,3)),new THREE.PointsMaterial({color:0x918d8d,size:.02,transparent:true,opacity:.3}));stage.add(particles);
  const server=new THREE.Group();stage.add(server);
  mesh(new THREE.CylinderGeometry(1.42,1.7,.23,64),metal(0x272626),server,0,0,0);
  mesh(new THREE.CylinderGeometry(1.2,1.42,.16,64),metal(0x454242),server,0,.19,0);
  ring(server,1.43,.18,palette.cyan,.45);ring(server,1.2,.29,palette.cyan,.2);
  for(let i=0;i<3;i++) {
    box(server,1.38,.36,.95,0x454242,0,.59+i*.39,0);
    box(server,1.28,.04,.94,0x918d8d,0,.77+i*.39,0);
    box(server,.43,.045,.02,0xbbbbbb,-.23,.59+i*.39,.486,0x444444);
    for(let j=0;j<3;j++)box(server,.025,.025,.021,palette.online,.28+j*.09,.59+i*.39,.49,palette.online);
  }
  // Extruded protection emblem above the central licensing service.
  const shieldShape=new THREE.Shape();shieldShape.moveTo(0,.68);shieldShape.lineTo(.55,.45);shieldShape.lineTo(.48,-.17);shieldShape.quadraticCurveTo(.3,-.48,0,-.7);shieldShape.quadraticCurveTo(-.3,-.48,-.48,-.17);shieldShape.lineTo(-.55,.45);shieldShape.closePath();
  const shield=new THREE.Group();shield.position.set(0,2.55,0);server.add(shield);
  const shieldMesh=mesh(new THREE.ExtrudeGeometry(shieldShape,{depth:.12,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:.045,bevelThickness:.025}),metal(0x918d8d,0x111111,.94),shield);
  const shieldOutline=new THREE.LineSegments(new THREE.EdgesGeometry(shieldMesh.geometry),new THREE.LineBasicMaterial({color:0xffffff,transparent:true,opacity:.6}));shield.add(shieldOutline);
  const checkPoints=[new THREE.Vector3(-.24,-.03,.18),new THREE.Vector3(-.04,-.23,.18),new THREE.Vector3(.3,.22,.18)];
  const check=new THREE.Line(new THREE.BufferGeometry().setFromPoints(checkPoints),new THREE.LineBasicMaterial({color:0xffffff}));shield.add(check);
  label('LICENSING SERVER',new THREE.Vector3(0,-.38,1.8),null,'server-label');
  function release(group) {const geometries=new Set(),materials=new Set();group.traverse(object=>{if(object.geometry)geometries.add(object.geometry);if(object.material){for(const m of Array.isArray(object.material)?object.material:[object.material])materials.add(m);}});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());group.clear();}
  function rebuild(data) {
    release(devicesGroup);entries.length=0;hitMeshes=[];labels.splice(1).forEach(l=>l.element.remove());
    data.forEach((d,i)=>{
      const revoked=d.effective_status==='REVOKED',isRecent=d.last_seen&&(Date.now()-new Date(d.last_seen).getTime()<86400000);
      const color=revoked?palette.revoked:d.detection==='NEW'?palette.new:d.online?palette.online:isRecent?palette.new:palette.offline;
      const ringIndex=data.length>10?Math.floor(i/8):0,count=data.length>10?Math.min(8,data.length-ringIndex*8):data.length;
      const angle=(i%8)/Math.max(1,count)*Math.PI*2 + ringIndex*.35 + .2;
      // With <=10 nodes use the complete circle; outer rings keep larger fleets legible.
      const theta=data.length>10?angle:i/Math.max(1,data.length)*Math.PI*2+.2;
      const radius=data.length>10?3.6+ringIndex*1.85:4.5;
      const position=new THREE.Vector3(Math.cos(theta)*radius,.05,Math.sin(theta)*radius);
      const device=new THREE.Group();device.position.copy(position);device.rotation.y=Math.atan2(camera.position.x-position.x,camera.position.z-position.z);devicesGroup.add(device);
      mesh(new THREE.CylinderGeometry(.64,.78,.1,32),metal(0x272626),device,0,0,0);const baseRing=ring(device,.69,.07,color,.5);
      box(device,.83,.56,.12,0x646060,0,.8,0);
      box(device,.7,.43,.015,0x151515,0,.8,.07,color);
      box(device,.58,.014,.022,color,0,.89,.085,color);box(device,.38,.014,.022,color,-.1,.8,.085,color);
      box(device,.24,.08,.1,0x918d8d,0,.45,0);box(device,.48,.05,.3,0x646060,0,.36,.05);
      const led=mesh(new THREE.SphereGeometry(.045,12,8),new THREE.MeshBasicMaterial({color}),device,.29,.65,.082);
      if(revoked){const a=box(device,.3,.022,.024,color,0,.81,.105,color);a.rotation.z=.7;const b=box(device,.3,.022,.024,color,0,.81,.11,color);b.rotation.z=-.7;}
      device.traverse(obj=>{if(obj.isMesh){obj.userData.deviceId=d.device_id;hitMeshes.push(obj);}});
      const start=new THREE.Vector3(0,.38,0),end=position.clone().add(new THREE.Vector3(0,.18,0));
      const mid=start.clone().lerp(end,.5);mid.y=.65;
      const curve=new THREE.QuadraticBezierCurve3(start,mid,end);
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(48)),new THREE.LineBasicMaterial({color,transparent:true,opacity:revoked?.27:d.online?.5:.18}));devicesGroup.add(line);
      const signal=mesh(new THREE.SphereGeometry(.055,10,8),new THREE.MeshBasicMaterial({color}),devicesGroup);signal.visible=d.online && !revoked;
      const text=label(d.device_id.slice(0,8),position.clone().add(new THREE.Vector3(0,-.18,.7)),d.device_id);
      entries.push({id:d.device_id,device,baseRing,line,signal,curve,text,color,d,index:i});
    });
    applySelection();resize();
  }
  function applySelection(){for(const e of entries){const selected=e.id===selection;e.baseRing.material.opacity=selected?1:.5;e.line.material.opacity=selected?.95:e.d.effective_status==='REVOKED'?.27:e.d.online?.5:.18;e.line.material.color.setHex(selected?palette.cyan:e.color);e.text.element.style.color=selected?'#acfff0':'';e.device.scale.setScalar(selected?1.12:1);}}
  function render(time=performance.now()) {
    if(disposed)return;
    if(!paused && !reducedMotion){phase+=Math.min(.05,(time-lastFrame)/1000 || .033);pointer.lerp(targetPointer,.045);camera.position.set(10+pointer.x*.75,11+pointer.y*.3,15-pointer.x*.5);camera.lookAt(0,.3,0);shield.rotation.y=Math.sin(phase*.35)*.32;particles.rotation.y=Math.sin(phase*.05)*.015;for(const e of entries)if(e.signal.visible)e.signal.position.copy(e.curve.getPoint((phase*.19+e.index*.19)%1));}
    else {for(const e of entries)if(e.signal.visible)e.signal.position.copy(e.curve.getPoint(.5));}
    lastFrame=time;renderer.render(scene,camera);
    for(const l of labels){projected.copy(l.position).project(camera);l.element.style.left=`${(projected.x*.5+.5)*host.clientWidth}px`;l.element.style.top=`${(-projected.y*.5+.5)*host.clientHeight}px`;l.element.hidden=projected.z>1 || projected.z< -1;}
  }
  function loop(time){frame=0;if(disposed || !visible || document.hidden)return;if(time-lastFrame>32)render(time);frame=requestAnimationFrame(loop);}
  function schedule(){cancelAnimationFrame(frame);frame=0;if(disposed)return;if(!visible || document.hidden){onState('3D paused while out of view');return;}render();if(!paused && !reducedMotion){onState('Recorded heartbeat paths · 3D interactive');frame=requestAnimationFrame(loop);}else onState(reducedMotion?'Reduced motion · static 3D view':'Motion paused · device selection available');}
  function resize(){if(disposed)return;const w=host.clientWidth,h=host.clientHeight;if(!w || !h)return;renderer.setSize(w,h,false);camera.aspect=w/h;
    camera.fov=w/h<1.4?46:36;camera.updateProjectionMatrix();render();}
  function hit(event){const bounds=canvas.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((event.clientX-bounds.left)/bounds.width*2-1,-(event.clientY-bounds.top)/bounds.height*2+1),camera);const hits=raycaster.intersectObjects(hitMeshes,false);return hits[0]?.object.userData.deviceId;}
  function move(event){if(event.pointerType!=='mouse')return;const bounds=canvas.getBoundingClientRect();targetPointer.set((event.clientX-bounds.left)/bounds.width-.5,(event.clientY-bounds.top)/bounds.height-.5);const id=hit(event),d=records.find(d=>d.device_id===id);canvas.style.cursor=id?'pointer':'default';tooltip.hidden=!d;
    if(d){const title=document.createElement('strong');title.textContent=d.customer || 'Unassociated installation';const summary=document.createElement('small');summary.textContent=`${d.device_id.slice(0,8)} · App ${d.app_version}`;const status=document.createElement('small');const isRecent=d.last_seen&&(Date.now()-new Date(d.last_seen).getTime()<86400000);status.textContent=`${d.online?'Online within threshold':isRecent?'Recently online':'Offline'} · ${d.effective_status.toLowerCase().replaceAll('_',' ')}`;tooltip.replaceChildren(title,summary,status);}
  }
  function leave(){targetPointer.set(0,0);tooltip.hidden=true;canvas.style.cursor='default';}
  function click(event){const id=hit(event);if(id){selection=id;applySelection();render();onSelect(id);}}
  function contextLost(event){event.preventDefault();if(!disposed)onFailure();}
  canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerleave',leave);canvas.addEventListener('click',click);canvas.addEventListener('webglcontextlost',contextLost);
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(host);
  const visibility=()=>schedule();document.addEventListener('visibilitychange',visibility);
  resize();schedule();
  return {
    update(data){records=data;const next=JSON.stringify(data.map(d=>[d.device_id,d.online,d.detection,d.effective_status,d.app_version,d.customer]));if(next!==signature){signature=next;rebuild(data);}schedule();},
    select(id){selection=id;applySelection();render();},
    setVisible(value){visible=value;schedule();},
    setMotion(value,reduced){paused=value;reducedMotion=reduced;schedule();},
    dispose(){if(disposed)return;disposed=true;cancelAnimationFrame(frame);resizeObserver.disconnect();document.removeEventListener('visibilitychange',visibility);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerleave',leave);canvas.removeEventListener('click',click);canvas.removeEventListener('webglcontextlost',contextLost);labels.forEach(l=>l.element.remove());release(devicesGroup);release(stage);renderer.dispose();renderer.forceContextLoss();canvas.remove();tooltip.hidden=true;}
  };
}
