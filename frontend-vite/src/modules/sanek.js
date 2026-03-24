import { G, ae } from './state.js';
import { $, esc } from './utils.js';
import { api, API_BASE } from './api.js';

// ===================== SANEK CHAT + AVATAR =====================
G._snOpen=false;G._snSid=null;G._snSending=false;G._snMsgCount=0;G._snHistOpen=false;var _snAbort=null;

// === SANEK AVATAR ENGINE (from sanek_v4) ===
var _sn={
  state:'idle',time:0,
  eyeX:0,eyeY:0,targetEyeX:0,targetEyeY:0,
  bounceY:0,squishX:1,squishY:1,tSquishX:1,tSquishY:1,
  blinkTimer:0,blinkOpen:1,mouthOpen:0,tMouthOpen:0,
  emotionT:0,keystrokeImpact:0,readingNod:0,
  color:{r:93,g:228,b:255},
  tColor:{r:93,g:228,b:255}
};

var _snColorsDark={
  idle:{r:93,g:228,b:255},reading:{r:251,g:146,b:60},listening:{r:255,g:190,b:74},
  thinking:{r:167,g:139,b:250},alert:{r:255,g:107,b:129},success:{r:74,g:222,b:128},sleeping:{r:100,g:116,b:139}
};
var _snColorsLight={
  idle:{r:167,g:139,b:250},reading:{r:251,g:146,b:60},listening:{r:255,g:190,b:74},
  thinking:{r:129,g:140,b:248},alert:{r:255,g:107,b:129},success:{r:74,g:222,b:128},sleeping:{r:140,g:156,b:179}
};
var _snGlowsDark={
  idle:'rgba(93,228,255,.15)',reading:'rgba(251,146,60,.18)',listening:'rgba(255,190,74,.2)',
  thinking:'rgba(167,139,250,.15)',alert:'rgba(255,107,129,.15)',success:'rgba(74,222,128,.2)',sleeping:'rgba(100,116,139,.06)'
};
var _snGlowsLight={
  idle:'rgba(109,40,217,.15)',reading:'rgba(217,119,6,.18)',listening:'rgba(180,83,9,.2)',
  thinking:'rgba(79,70,229,.15)',alert:'rgba(220,38,38,.15)',success:'rgba(5,150,105,.2)',sleeping:'rgba(100,116,139,.06)'
};
var _snTagColorsDark={idle:'#5de4ff',reading:'#fb923c',listening:'#ffbe4a',thinking:'#a78bfa',alert:'#ff6b81',success:'#4ade80',sleeping:'#64748b'};
var _snTagColorsLight={idle:'#6d28d9',reading:'#d97706',listening:'#b45309',thinking:'#4f46e5',alert:'#dc2626',success:'#059669',sleeping:'#64748b'};
var _snColors=_snColorsDark,_snGlows=_snGlowsDark,_snTagColors=_snTagColorsDark;
var _snLabels={
  idle:'готов — жду команды',reading:'читаю — вижу что пишешь...',listening:'слушаю — говори...',
  thinking:'думаю — анализирую...',alert:'ошибка — требуется внимание',success:'готово — задача выполнена!',sleeping:'сон — нет подключения'
};
var _snIsLightTheme=false;
function _snUpdateThemeColors(){
  var lt=document.documentElement.getAttribute('data-theme')==='light';
  _snIsLightTheme=lt;
  _snColors=lt?_snColorsLight:_snColorsDark;
  _snGlows=lt?_snGlowsLight:_snGlowsDark;
  _snTagColors=lt?_snTagColorsLight:_snTagColorsDark;
  var tc={..._snColors[_sn.state]};
  _sn.tColor=tc;
  _sn.color={r:tc.r,g:tc.g,b:tc.b};
  // Update status UI colors
  var st=$('snStatusText');if(st)st.style.color=_snTagColors[_sn.state];
  var dot=$('snStatusDot');if(dot){dot.style.background=_snTagColors[_sn.state];dot.style.boxShadow='0 0 6px '+_snTagColors[_sn.state]}
  var hds=document.querySelector('.sn-hd-status');if(hds)hds.style.color=_snTagColors[_sn.state];
}

function _snLerp(a,b,t){return a+(b-a)*t}
function _snLerpC(c,t,s){c.r=_snLerp(c.r,t.r,s);c.g=_snLerp(c.g,t.g,s);c.b=_snLerp(c.b,t.b,s)}
function _snRgb(c,a){return a!==undefined?`rgba(${Math.round(c.r)},${Math.round(c.g)},${Math.round(c.b)},${a})`:`rgb(${Math.round(c.r)},${Math.round(c.g)},${Math.round(c.b)})`}

function snSetState(state){
  _sn.state=state;_sn.tColor={..._snColors[state]};_sn.emotionT=0;
  var st=$('snStatusText');if(st){st.textContent=_snLabels[state];st.style.color=_snTagColors[state]}
  var dot=$('snStatusDot');if(dot){dot.style.background=_snTagColors[state];dot.style.boxShadow='0 0 6px '+_snTagColors[state]}
  var hds=document.querySelector('.sn-hd-status');if(hds)hds.style.color=_snTagColors[state];
  _sn.tSquishX=1.12;_sn.tSquishY=.9;
  setTimeout(()=>{_sn.tSquishX=.94;_sn.tSquishY=1.08},120);
  setTimeout(()=>{_sn.tSquishX=1;_sn.tSquishY=1},280);
  if(state==='success')_sn.bounceY=-20;
}

function _snDrawBody(c,ox,oy,s){
  var S=_sn,t=S.time,col=S.color,headR=150;
  var lt=_snIsLightTheme;
  // Shadow
  c.save();c.translate(ox,oy+20);c.scale(1,.25);
  var shG=c.createRadialGradient(0,0,0,0,0,headR*.8);shG.addColorStop(0,lt?'rgba(0,0,0,.2)':'rgba(0,0,0,.25)');shG.addColorStop(1,'rgba(0,0,0,0)');
  c.fillStyle=shG;c.beginPath();c.arc(0,0,headR*.8,0,Math.PI*2);c.fill();c.restore();
  // Antenna
  var aw=Math.sin(t*2.5)*4+S.keystrokeImpact*Math.sin(t*20)*6;
  c.save();c.strokeStyle=_snRgb(col,lt?.7:.5);c.lineWidth=4;c.lineCap='round';
  c.beginPath();c.moveTo(ox,oy-headR+10);c.quadraticCurveTo(ox+aw,oy-headR-25,ox+aw*.5,oy-headR-45);c.stroke();
  var tx=ox+aw*.5,ty=oy-headR-45,tr=7+Math.sin(t*3)*2;
  var tG=c.createRadialGradient(tx,ty,0,tx,ty,tr*3);tG.addColorStop(0,_snRgb(col,.8));tG.addColorStop(.5,_snRgb(col,.2));tG.addColorStop(1,_snRgb(col,0));
  c.fillStyle=tG;c.beginPath();c.arc(tx,ty,tr*3,0,Math.PI*2);c.fill();
  c.fillStyle=_snRgb(col);c.beginPath();c.arc(tx,ty,tr,0,Math.PI*2);c.fill();c.restore();
  // Head
  var hG=c.createRadialGradient(ox-30,oy-40,0,ox,oy,headR);
  if(lt){hG.addColorStop(0,'#2a3660');hG.addColorStop(1,'#171e38')}
  else{hG.addColorStop(0,'#2e3a5c');hG.addColorStop(1,'#1a2240')}
  c.fillStyle=hG;c.beginPath();c.ellipse(ox,oy,headR,headR*.95,0,0,Math.PI*2);c.fill();
  // Highlight (specular)
  var hlG=c.createRadialGradient(ox-40,oy-50,0,ox-40,oy-50,headR*.8);hlG.addColorStop(0,'rgba(255,255,255,.1)');hlG.addColorStop(1,'rgba(255,255,255,0)');
  c.fillStyle=hlG;c.beginPath();c.ellipse(ox,oy,headR,headR*.95,0,0,Math.PI*2);c.fill();
  // Head outline — bright accent border
  c.strokeStyle=_snRgb(col,.5);c.lineWidth=3;c.beginPath();c.ellipse(ox,oy,headR,headR*.95,0,0,Math.PI*2);c.stroke();
  // Panel lines (robot detail)
  c.save();c.strokeStyle=lt?'rgba(255,255,255,.06)':'rgba(255,255,255,.05)';c.lineWidth=1.5;
  c.beginPath();c.moveTo(ox-headR*.6,oy-headR*.55);c.quadraticCurveTo(ox,oy-headR*.7,ox+headR*.6,oy-headR*.55);c.stroke();
  c.beginPath();c.moveTo(ox,oy-headR*.65);c.lineTo(ox,oy-headR*.95);c.stroke();
  // Side vents
  [-1,1].forEach(function(side){
    for(var i=0;i<3;i++){
      c.beginPath();c.moveTo(ox+side*(headR*.7),oy+30+i*10);c.lineTo(ox+side*(headR*.85),oy+30+i*10);c.stroke();
    }
  });
  c.restore();
  // Inner edge shading (rim)
  var rimG=c.createRadialGradient(ox,oy,headR*.75,ox,oy,headR);
  rimG.addColorStop(0,'rgba(0,0,0,0)');rimG.addColorStop(1,lt?'rgba(0,0,0,.12)':'rgba(0,0,0,.15)');
  c.fillStyle=rimG;c.beginPath();c.ellipse(ox,oy,headR,headR*.95,0,0,Math.PI*2);c.fill();
  // Brightness multiplier: both themes have dark heads, features must be bright
  var B=1.6;
  function _a(v){return Math.min(v*B,1)}
  // Cheeks
  var cA=S.state==='success'?.25:S.state==='listening'?.2:S.state==='reading'?.15:.08;
  [-1,1].forEach(function(side){
    var cG=c.createRadialGradient(ox+side*105,oy+35,0,ox+side*105,oy+35,30);cG.addColorStop(0,_snRgb(col,_a(cA)));cG.addColorStop(1,_snRgb(col,0));
    c.fillStyle=cG;c.beginPath();c.ellipse(ox+side*105,oy+35,30,22,0,0,Math.PI*2);c.fill();
  });
  // Eyes
  var eS=55,eY=oy-15;
  [-1,1].forEach(function(side){
    var ex=ox+side*eS+S.eyeX,ey=eY+S.eyeY;
    var sW=S.state==='listening'?52:S.state==='reading'?48:46;
    var sH=S.state==='listening'?52:S.state==='reading'?44:46;
    c.fillStyle='rgba(0,8,24,.45)';c.beginPath();c.ellipse(ex,ey,sW,sH*S.blinkOpen,0,0,Math.PI*2);c.fill();
    if(S.blinkOpen>.15){
      var iR=S.state==='listening'?28:S.state==='alert'?22:S.state==='reading'?22:24;
      var iG=c.createRadialGradient(ex,ey,0,ex,ey,iR*2.2);iG.addColorStop(0,_snRgb(col,_a(.5)));iG.addColorStop(1,_snRgb(col,0));
      c.fillStyle=iG;c.beginPath();c.arc(ex,ey,iR*2.2,0,Math.PI*2);c.fill();
      c.fillStyle=_snRgb(col);c.beginPath();c.arc(ex,ey,iR,0,Math.PI*2);c.fill();
      var inG=c.createRadialGradient(ex,ey,iR*.2,ex,ey,iR);inG.addColorStop(0,'rgba('+Math.round(col.r*.3)+','+Math.round(col.g*.3)+','+Math.round(col.b*.3)+',.5)');inG.addColorStop(1,'rgba(0,0,0,0)');
      c.fillStyle=inG;c.beginPath();c.arc(ex,ey,iR,0,Math.PI*2);c.fill();
      var pR=S.state==='alert'?7:S.state==='reading'?6:S.state==='listening'?10:8;
      c.fillStyle='#050810';c.beginPath();c.arc(ex+S.eyeX*.3,ey+S.eyeY*.3,pR,0,Math.PI*2);c.fill();
      c.fillStyle='rgba(255,255,255,.9)';c.beginPath();c.arc(ex+8,ey-8,6,0,Math.PI*2);c.fill();
      c.fillStyle='rgba(255,255,255,.6)';c.beginPath();c.arc(ex-5,ey+6,3,0,Math.PI*2);c.fill();
    }
    if(S.blinkOpen<.3){
      c.strokeStyle=_snRgb(col,_a(.6));c.lineWidth=4;c.lineCap='round';c.beginPath();
      if(S.state==='success')c.arc(ex,ey+5,22,Math.PI,0);else{c.moveTo(ex-22,ey);c.lineTo(ex+22,ey)}c.stroke();
    }
  });
  // Eyebrows
  if(S.state==='alert'){c.strokeStyle=_snRgb(col,_a(.8));c.lineWidth=5;c.lineCap='round';[-1,1].forEach(function(side){var bx=ox+side*eS,by=eY-48;c.beginPath();c.moveTo(bx-side*22,by+6);c.lineTo(bx+side*22,by-4);c.stroke()})}
  if(S.state==='thinking'){c.strokeStyle=_snRgb(col,_a(.5));c.lineWidth=4;c.lineCap='round';var lbx=ox-eS,rbx=ox+eS,by=eY-48;c.beginPath();c.moveTo(lbx-22,by+4);c.lineTo(lbx+22,by-8);c.stroke();c.beginPath();c.moveTo(rbx-22,by-2);c.lineTo(rbx+22,by+2);c.stroke()}
  if(S.state==='reading'){c.strokeStyle=_snRgb(col,_a(.5));c.lineWidth=4;c.lineCap='round';[-1,1].forEach(function(side){var bx=ox+side*eS,by=eY-46;c.beginPath();c.moveTo(bx-20,by+2);c.quadraticCurveTo(bx,by-5,bx+20,by+1);c.stroke()})}
  // Mouth
  var mY=oy+55;
  if(S.state==='success'){c.strokeStyle=_snRgb(col,_a(.9));c.lineWidth=4;c.lineCap='round';c.beginPath();c.arc(ox,mY-10,35,.15,Math.PI-.15);c.stroke();if(S.mouthOpen>.4){c.fillStyle='#ff8ba7';c.beginPath();c.ellipse(ox,mY+4,14,8*S.mouthOpen,0,0,Math.PI);c.fill()}}
  else if(S.state==='alert'){c.strokeStyle=_snRgb(col,_a(.7));c.lineWidth=3.5;c.lineCap='round';c.beginPath();c.moveTo(ox-18,mY);c.lineTo(ox+18,mY);c.stroke()}
  else if(S.state==='listening'){c.fillStyle='rgba(0,8,24,.35)';c.beginPath();c.ellipse(ox,mY,16,12+S.mouthOpen*14,0,0,Math.PI*2);c.fill();c.strokeStyle=_snRgb(col,_a(.5));c.lineWidth=2;c.beginPath();c.ellipse(ox,mY,16,12+S.mouthOpen*14,0,0,Math.PI*2);c.stroke()}
  else if(S.state==='thinking'){c.strokeStyle=_snRgb(col,_a(.6));c.lineWidth=3.5;c.lineCap='round';var mW=Math.sin(t*1.5)*3;c.beginPath();c.moveTo(ox-15,mY+mW);c.quadraticCurveTo(ox,mY-8+mW,ox+20,mY+2+mW);c.stroke()}
  else if(S.state==='reading'){c.strokeStyle=_snRgb(col,_a(.6));c.lineWidth=3;c.lineCap='round';var mP=S.keystrokeImpact*2;c.beginPath();c.moveTo(ox-14,mY-1);c.quadraticCurveTo(ox,mY+5+mP,ox+14,mY-1);c.stroke()}
  else if(S.state==='sleeping'){c.strokeStyle=_snRgb(col,_a(.3));c.lineWidth=2.5;c.lineCap='round';c.beginPath();c.arc(ox,mY+4,12,.3,Math.PI-.3);c.stroke()}
  else{c.strokeStyle=_snRgb(col,_a(.7));c.lineWidth=3.5;c.lineCap='round';c.beginPath();c.arc(ox,mY-6,26,.25,Math.PI-.25);c.stroke()}
  // Reading text lines
  if(S.state==='reading'){var lY=oy+100,lW=[50,65,40,55,35],cur=Math.floor((Math.sin(t*1.8)+1)/2*4.99);lW.forEach(function(w,i){c.fillStyle=_snRgb(col,_a(i===cur?.4:.1));c.beginPath();c.roundRect?c.roundRect(ox-35,lY+i*10,w,4,2):(c.rect(ox-35,lY+i*10,w,4));c.fill()});if(Math.sin(t*6)>0){c.fillStyle=_snRgb(col,_a(.7));c.fillRect(ox-35+lW[cur]+3,lY+cur*10-1,2,6)}}
  // Thinking bubbles
  if(S.state==='thinking'){[{x:95,y:-80,r:6+Math.sin(t*2)*1},{x:115,y:-105,r:9+Math.sin(t*2+1)*1.5},{x:130,y:-135,r:13+Math.sin(t*2+2)*2}].forEach(function(b,i){c.fillStyle=_snRgb(col,_a(.15+i*.1+Math.sin(t*1.5+i)*.05));c.beginPath();c.arc(ox+b.x,oy+b.y+Math.sin(t+i)*4,b.r,0,Math.PI*2);c.fill()})}
  // Alert ring
  if(S.state==='alert'){var ap=(Math.sin(t*4)+1)/2;c.strokeStyle=_snRgb(col,_a(.1+ap*.15));c.lineWidth=3;c.setLineDash([8,8]);c.lineDashOffset=-t*40;c.beginPath();c.ellipse(ox,oy,headR+15,headR*.95+15,0,0,Math.PI*2);c.stroke();c.setLineDash([]);var bdX=ox+110,bdY=oy-100;c.fillStyle=_snRgb(col,_a(.9));c.beginPath();c.arc(bdX,bdY,18,0,Math.PI*2);c.fill();c.fillStyle='#fff';c.font='bold 22px sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillText('!',bdX,bdY+1)}
  // Listening waves
  if(S.state==='listening'){for(var i=0;i<12;i++){var h=8+Math.abs(Math.sin(t*5+i*.8))*22,a=_a(.4+Math.abs(Math.sin(t*5+i*.8))*.5);c.fillStyle=_snRgb(col,a);var bx=ox-60+i*10;c.beginPath();c.roundRect?c.roundRect(bx,oy+105-h/2,6,h,3):(c.fillRect(bx,oy+105-h/2,6,h));c.fill()}}
  // Sleeping Zzz
  if(S.state==='sleeping'){c.textAlign='center';[{x:85,y:-60,s:18,d:0},{x:105,y:-90,s:24,d:.6},{x:120,y:-125,s:30,d:1.2}].forEach(function(z,i){var t2=(t*.7+z.d)%3,a=_a(t2<2?Math.sin(t2/2*Math.PI)*.5:0),dr=Math.sin(t*.5+i)*5;c.fillStyle=_snRgb(col,a);c.font='800 '+z.s+'px sans-serif';c.fillText('z',ox+z.x+dr,oy+z.y-t2*8)})}
  // Success sparkles
  if(S.state==='success'){for(var i=0;i<6;i++){var ang=(Math.PI*2/6)*i+t*.5,dist=headR+25+Math.sin(t*2+i)*10,sx=ox+Math.cos(ang)*dist,sy=oy+Math.sin(ang)*dist*.85,sa2=_a(.3+Math.sin(t*3+i*1.5)*.3),sr=3+Math.sin(t*4+i)*2;c.fillStyle=_snRgb(col,sa2);c.beginPath();for(var j=0;j<4;j++){var sa=(Math.PI/2)*j+t*2,sr2=j%2===0?sr*2.5:sr*.5,px=sx+Math.cos(sa)*sr2,py=sy+Math.sin(sa)*sr2;j===0?c.moveTo(px,py):c.lineTo(px,py)}c.closePath();c.fill()}}
}

// Animation tick
function _snTick(){
  var S=_sn;S.time+=.016;S.emotionT=Math.min(S.emotionT+.016,10);
  _snLerpC(S.color,S.tColor,.06);
  // Eye behavior per state
  if(S.state==='reading'){var rs=1.8+Math.sin(S.time*.3)*.3;S.eyeX=_snLerp(S.eyeX,Math.sin(S.time*rs)*16,.12);S.eyeY=_snLerp(S.eyeY,10+Math.sin(S.time*.6)*2,.08);S.readingNod=Math.sin(S.time*1.2)*.03}
  else if(S.state==='thinking'){S.eyeX=_snLerp(S.eyeX,Math.sin(S.time*.7)*14,.04);S.eyeY=_snLerp(S.eyeY,-10+Math.cos(S.time*.5)*4,.04);S.readingNod=_snLerp(S.readingNod,0,.05)}
  else if(S.state==='idle'||S.state==='alert'||S.state==='success'){S.eyeX=_snLerp(S.eyeX,S.targetEyeX*12,.08);S.eyeY=_snLerp(S.eyeY,S.targetEyeY*8,.08);S.readingNod=_snLerp(S.readingNod,0,.05)}
  else{S.eyeX=_snLerp(S.eyeX,0,.05);S.eyeY=_snLerp(S.eyeY,0,.05);S.readingNod=_snLerp(S.readingNod,0,.05)}
  S.keystrokeImpact=_snLerp(S.keystrokeImpact,0,.15);
  S.squishX=_snLerp(S.squishX,S.tSquishX,.12);S.squishY=_snLerp(S.squishY,S.tSquishY,.12);
  S.bounceY=_snLerp(S.bounceY,0,.08);
  // Blink
  S.blinkTimer+=.016;
  if(S.state==='sleeping')S.blinkOpen=_snLerp(S.blinkOpen,0,.1);
  else if(S.state==='success')S.blinkOpen=_snLerp(S.blinkOpen,.35,.1);
  else if(S.state==='reading'){if(S.blinkTimer>6+Math.random()*3){S.blinkTimer=0;S.blinkOpen=0}if(S.blinkOpen<.5)S.blinkOpen=_snLerp(S.blinkOpen,1,.3)}
  else{if(S.blinkTimer>3+Math.random()*2){S.blinkTimer=0;S.blinkOpen=0}if(S.blinkOpen<.5)S.blinkOpen=_snLerp(S.blinkOpen,1,.25)}
  // Mouth
  if(S.state==='listening')S.tMouthOpen=.3+Math.abs(Math.sin(S.time*6))*.5;
  else if(S.state==='success')S.tMouthOpen=.7;
  else if(S.state==='alert')S.tMouthOpen=.15;
  else if(S.state==='reading')S.tMouthOpen=.05+S.keystrokeImpact*.15;
  else S.tMouthOpen=0;
  S.mouthOpen=_snLerp(S.mouthOpen,S.tMouthOpen,.1);
}

// Draw on multiple canvases
function _snDraw(){
  _snTick();
  var S=_sn,fY=Math.sin(S.time*.8)*6;
  // Header mini canvas — full Sanek with antenna
  var mc=$('snMiniCanvas');
  if(mc&&mc.offsetParent!==null){var ctx2=mc.getContext('2d');ctx2.clearRect(0,0,320,320);ctx2.save();ctx2.translate(160,172);ctx2.scale(.45,.45);_snDrawBody(ctx2,0,0,.45);ctx2.restore()}
  // Button canvas — clean, no glow bleed
  var bc=$('snBtnCanvas');
  if(bc){var ctx3=bc.getContext('2d');ctx3.clearRect(0,0,192,192);ctx3.save();ctx3.beginPath();ctx3.arc(96,96,95,0,Math.PI*2);ctx3.clip();ctx3.translate(96,104+fY*.3);ctx3.scale(.32,.32);_snDrawBody(ctx3,0,0,.32);ctx3.restore()}
  requestAnimationFrame(_snDraw);
}

// Mouse tracking for eyes
document.addEventListener('mousemove',function(e){
  var btn=$('sanekBtn');if(!btn)return;
  var r=btn.getBoundingClientRect(),cx=r.left+r.width/2,cy=r.top+r.height/2;
  _sn.targetEyeX=Math.max(-1,Math.min(1,(e.clientX-cx)/300*2));
  _sn.targetEyeY=Math.max(-1,Math.min(1,(e.clientY-cy)/300*2));
});

// Start avatar loop
_snUpdateThemeColors();
_snDraw();

// === CHAT LOGIC ===
function toggleSanek(){
  G._snOpen=!G._snOpen;
  $('sanekPanel').classList.toggle('open',G._snOpen);
  $('sanekBtn').style.display=G._snOpen?'none':'';
  if(G._snOpen){$('sanekInput').focus();_snUpdateCtxBadge()}
  if(!G._snOpen&&G._snHistOpen)_snToggleHistory();
}

function sanekNewSession(){
  G._snSid=null;G._snMsgCount=0;_snUpdateCounter();snSetState('idle');
  if(G._snHistOpen)_snToggleHistory();
  $('sanekMessages').innerHTML='<div class="sn-welcome"><div class="sn-welcome-line"></div><h3>Чем могу помочь?</h3><p>Мониторинг, аналитика, отчёты,<br>экономика и управление — спрашивай.</p><div class="sn-hints"><div class="sn-hints-label fast">⚡ Быстрые запросы</div><button class="sn-hint" onclick="sanekHint(this)">📋 Сводка по всем объектам</button><button class="sn-hint" onclick="sanekHint(this)">🚨 Активные аварии</button><button class="sn-hint" onclick="sanekHint(this)">⚡ Выработка и потребление за сутки</button><button class="sn-hint" onclick="sanekHint(this)">💰 Экономика за неделю</button><div class="sn-hints-label deep">🔬 Аналитика и отчёты</div><button class="sn-hint" onclick="sanekHint(this)">📊 KPI отчёт в Excel за 7 дней</button><button class="sn-hint" onclick="sanekHint(this)">🔍 Анализ инцидентов за сутки</button><button class="sn-hint" onclick="sanekHint(this)">📈 Тренд потребления за 24 часа</button><button class="sn-hint" onclick="sanekHint(this)">🔧 Когда ТО генераторов?</button></div></div>';
  _snUpdateCtxBadge();
}

function sanekHint(el){
  // Strip leading emoji + space from hint text
  $('sanekInput').value=el.textContent.trim().replace(/^[\u{1F300}-\u{1FAD6}\u{2600}-\u{27BF}]\s*/u,'');
  sendToSanek();
}

// Typing detection — switches avatar to reading state
// NOTE: attached via setTimeout(0) because sanekInput is below this script in DOM
var _snTypingTimeout=null;
function _snInitTypingDetection(){
  var inp=$('sanekInput');
  if(!inp)return;
  inp.addEventListener('input',function(){
    _sn.keystrokeImpact=1;
    if(inp.value.length>0&&_sn.state!=='thinking'){snSetState('reading')}
    clearTimeout(_snTypingTimeout);
    _snTypingTimeout=setTimeout(function(){if(_sn.state==='reading'&&!inp.value.length)snSetState('idle')},2000);
  });
  inp.addEventListener('focus',function(){if(inp.value.length>0&&_sn.state==='idle')snSetState('reading')});
  inp.addEventListener('blur',function(){if(_sn.state==='reading')setTimeout(function(){if(_sn.state==='reading')snSetState('idle')},500)});
}
// _snInitTypingDetection() called from <script> after sanekInput in DOM

function _snAddMsg(role,text){
  var msgs=$('sanekMessages');
  var welcome=msgs.querySelector('.sn-welcome');
  if(welcome)welcome.remove();
  var div=document.createElement('div');
  div.className='sn-msg '+role;
  if(role==='error'){
    div.innerHTML='<div class="sn-bname">Санёк</div>'+_snFormatText(text);
  } else if(role==='assistant'){
    div.innerHTML='<div class="sn-bname">Санёк</div>'+_snFormatText(text);
  } else {
    div.textContent=text;
  }
  // Copy button
  var copyBtn=document.createElement('button');
  copyBtn.className='sn-copy-btn';copyBtn.title='Копировать';copyBtn.innerHTML='📋';
  copyBtn.onclick=function(){
    var ok=function(){copyBtn.innerHTML='✓';copyBtn.classList.add('copied');setTimeout(function(){copyBtn.innerHTML='📋';copyBtn.classList.remove('copied')},1500)};
    if(navigator.clipboard&&window.isSecureContext){
      navigator.clipboard.writeText(text).then(ok).catch(function(){});
    }else{
      var ta=document.createElement('textarea');ta.value=text;ta.style.cssText='position:fixed;left:-9999px';
      document.body.appendChild(ta);ta.select();
      try{document.execCommand('copy');ok()}catch(e){}
      document.body.removeChild(ta);
    }
  };
  div.appendChild(copyBtn);
  // Feedback buttons for assistant messages
  if(role==='assistant'){
    var fbDiv=document.createElement('div');fbDiv.className='sn-feedback';
    fbDiv.innerHTML='<button onclick="_snFeedback(this,\'up\')" title="Полезный ответ">👍</button><button onclick="_snFeedback(this,\'down\')" title="Неполезный ответ">👎</button>';
    div.appendChild(fbDiv);
  }
  msgs.appendChild(div);
  msgs.scrollTop=msgs.scrollHeight;
  return div;
}

function _snFormatText(text){
  var esc=function(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')};
  text=esc(text);
  // markdown formatting
  text=text.replace(/\*\*\s*$/gm,'');text=text.replace(/^\*\*\s*/gm,'');text=text.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
  text=text.replace(/`(.+?)`/g,'<code style="background:rgba(0,0,0,.25);padding:1px 5px;border-radius:4px">$1</code>');
  // download links — match [any text](/reports/file.ext) where file has known extension
  text=text.replace(/\[([^\]]*)\]\(\/reports\/([^)]+\.(xlsx|pdf|csv|png|jpg|zip))\)/gi,
    '<a href="/reports/$2" download class="sn-dl-btn" target="_blank">📥 $1</a>');
  // Also catch plain /reports/file.ext URLs not in markdown links
  text=text.replace(/(?<![("'])\/reports\/([\w\-]+\.(xlsx|pdf|csv|png|zip))/gi,
    '<a href="/reports/$1" download class="sn-dl-btn" target="_blank">📥 $1</a>');
  // markdown links
  text=text.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,'<a href="$2" target="_blank" style="color:#5de4ff">$1</a>');
  text=text.replace(/\[([^\]]+)\]\(\/([^)]+)\)/g,'<a href="/$2" target="_blank" style="color:#5de4ff">$1</a>');
  // highlight numbers with units
  text=text.replace(/(\d[\d\s,.]*)\s*(кВт[\*·]ч|кВтч|кВт|руб\.?|₽|тыс\.?\s*₽|тыс\.?\s*руб\.?|%|ч\b|мин\b|м³|МВт[\*·]?ч?|руб\/кВт[\*·]?ч)/g,'<span class="sn-num">$1 $2</span>');
  // generator status
  text=text.replace(/\b(Аварийный стоп|АВАРИЙ\w*)\b/gi,'<span class="sn-gen-stop">$1</span>');
  text=text.replace(/\b(РАБОТА ✅|РАБОТА✅)\b/g,'<span class="sn-gen-run">$1</span>');
  // ЭКОНОМИЯ / УБЫТОК badges — match with or without sn-num spans
  text=text.replace(/(ЭКОНОМИЯ|экономия|прибыль|выгода)(\s*[:.]?\s*[+]?)(<span class="sn-num">[^<]+<\/span>|[\d\s,.+\-]+\s*(?:руб|₽|тыс[.\s]*(?:₽|руб)))/gi,'<span class="sn-economy profit">$1$2$3</span>');
  text=text.replace(/(УБЫТ(?:ОК|КИ|ок|ки)|убыт(?:ок|ки)|перерасход|потери|ущерб)(\s*[:.]?\s*[-]?)(<span class="sn-num">[^<]+<\/span>|[\d\s,.+\-]+\s*(?:руб|₽|тыс[.\s]*(?:₽|руб)))/gi,'<span class="sn-economy loss">$1$2$3</span>');

  var lines=text.split('\n'),out=[],buf=[];
  var listStack=[];
  var inTable=false;
  var inBlock=false;
  var inReasoning=false;
  var flushBuf=function(){if(buf.length){out.push('<p>'+buf.join('<br>')+'</p>');buf=[]}};
  var closeLists=function(d){while(listStack.length>d){var t=listStack.pop();out.push(t.type==='ol'?'</ol>':'</ul>')}};
  var closeAllLists=function(){closeLists(0)};
  var closeTable=function(){if(inTable){out.push('</tbody></table></div>');inTable=false}};
  var closeBlock=function(){if(inBlock){out.push('</div>');inBlock=false}};
  var closeReasoning=function(){if(inReasoning){out.push('</div>');inReasoning=false}};

  // Section class by content
  var _secCls=function(t){
    t=t.replace(/<[^>]+>/g,'').toLowerCase();
    if(/мкз|моргауш/i.test(t)) return ' sn-site-mkz';
    if(/якз|ядрин/i.test(t)) return ' sn-site-ykz';
    if(/вывод|итог|резюме|заключен/i.test(t)) return ' sn-conclusion';
    if(/рекоменд/i.test(t)) return ' sn-conclusion';
    if(/генератор\s*\d/i.test(t)) return ' sn-gen';
    if(/потер|убыт|простой|ущерб/i.test(t)) return ' sn-loss';
    return '';
  };

  // Table helpers
  var _isTableRow=function(ln){var s=ln.replace(/<[^>]+>/g,'');return (s.split('|').length-1)>=2&&s.trim().length>5};
  var _isTableSep=function(ln){return /^[\s|:\-]+$/.test(ln.replace(/<[^>]+>/g,''))&&ln.indexOf('|')!==-1};
  var _tableRow=function(ln,hdr){
    var cells=ln.split('|').map(function(c){return c.trim()}).filter(function(c){return c});
    var tag=hdr?'th':'td';
    return '<tr>'+cells.map(function(c){return '<'+tag+'>'+c+'</'+tag+'>'}).join('')+'</tr>';
  };

  // Pre-scan for table blocks
  var tableLines={};
  var run=0,runStart=0;
  for(var p=0;p<lines.length;p++){
    if(_isTableRow(lines[p])||_isTableSep(lines[p])){if(run===0)runStart=p;run++}
    else{if(run>=2)for(var r=runStart;r<runStart+run;r++)tableLines[r]=true;run=0}
  }
  if(run>=2)for(var r=runStart;r<runStart+run;r++)tableLines[r]=true;

  // Check if a line is a section title
  var _isSectionTitle=function(ln){
    var s=ln.trim();
    // Bold-only line: <b>Title</b> or <b>Title</b>:
    if(/^<b>[^<]+<\/b>:?\s*$/.test(s)) return true;
    // Emoji + text ending with colon (under 60 chars)
    if(s.length<60&&/^[^\w\s<&]/.test(s)&&/:$/.test(s)) return true;
    // Lines like "Генератор 1:" or "Потери от простоя:" or "Рекомендации:"
    if(/^<b>[^<]*(?:генератор|потер|рекоменд|вывод|итог|экономик|анализ|сводк)[^<]*<\/b>/i.test(s)) return true;
    return false;
  };

  for(var i=0;i<lines.length;i++){
    var ln=lines[i];

    // 🧠 Reasoning block — collect all → lines into one styled block
    if(/🧠/.test(ln)){
      flushBuf();closeAllLists();closeTable();closeBlock();closeReasoning();
      out.push('<div class="sn-reasoning"><div class="sn-reasoning-title">'+ln.trim()+'</div>');
      inReasoning=true;
      continue;
    }
    if(inReasoning){
      if(/^→/.test(ln.trim())){
        out.push('<span class="sn-reasoning-line">'+ln.trim()+'</span>');
        continue;
      } else {
        closeReasoning();
      }
    }

    // Tables
    if(tableLines[i]){
      if(_isTableSep(ln))continue;
      flushBuf();closeAllLists();
      if(!inTable){out.push('<div class="sn-table-wrap"><table class="sn-table"><tbody>');out.push(_tableRow(ln,true));inTable=true}
      else out.push(_tableRow(ln,false));
      continue;
    }
    closeTable();

    // Horizontal rule
    if(/^[\-─━═]{3,}\s*$/.test(ln)){flushBuf();closeAllLists();out.push('<hr>');continue}
    // Markdown headers
    if(/^#{2,3}\s+/.test(ln)){flushBuf();closeAllLists();closeBlock();var cls=_secCls(ln);out.push('<div class="sn-section-title'+cls+'">'+ln.replace(/^#{2,3}\s+/,'')+'</div>');if(/sn-conclusion/.test(cls)){out.push('<div class="sn-recommend-block">');inBlock=true}continue}

    // Clarification block — "Варианты:", "Уточните:", "Выберите:" → clickable buttons
    if(/^(\*\*)?[🔹]?(Вариант|Уточни|Выбери|Период|Формат)/.test(ln.replace(/<[^>]+>/g,''))){
      flushBuf();closeAllLists();closeBlock();
      out.push('<div class="sanek-clarification-widget"><div class="sanek-clarification-question">'+ln.replace(/<[^>]+>/g,'').replace(/\*\*/g,'')+'</div><div class="sanek-clarification-options">');
      for(var ci=i+1;ci<lines.length;ci++){
        var cl=lines[ci].replace(/<[^>]+>/g,'').trim();
        if(!cl)continue;
        if(/^📌|^💬/.test(cl))break;
        // Lines starting with * or - or • are options
        if(/^[\*\-•]/.test(cl)){
          var optTxt=cl.replace(/^[\*\-•""\s]+/,'').replace(/[""\*]+$/,'').trim();
          if(optTxt.length>3&&optTxt.length<80){
            var optAttr=optTxt.replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;');
            out.push('<button class="sanek-option-btn" onclick="_snSelectOption(this,\''+optAttr+'\')">'+_snEscapeHtml(optTxt)+'</button>');
          }
        }
      }
      out.push('</div></div>');
      // Skip consumed option lines
      for(var cj=i+1;cj<lines.length;cj++){
        var cx=lines[cj].replace(/<[^>]+>/g,'').trim();
        if(!cx)continue;
        if(/^📌|^💬/.test(cx)){i=cj-1;break}
        if(/^[\*\-•]/.test(cx)){i=cj;continue}
        i=cj-1;break;
      }
      continue;
    }

    // Sources block — and collect remaining lines as clickable follow-up hints
    if(/📌/.test(ln)){flushBuf();closeAllLists();out.push('<div class="sn-sources">'+ln.trim()+'</div>');
      // Remaining lines after 📌 are follow-up suggestions → render as clickable buttons
      var followUps=[];
      for(var fi=i+1;fi<lines.length;fi++){
        var fl=lines[fi].trim();
        if(!fl||/^💬/.test(fl))continue;
        if(fl.length>5&&fl.length<60)followUps.push(fl);
      }
      if(followUps.length>=1){
        out.push('<div class="sn-followup-btns">');
        for(var fj=0;fj<followUps.length;fj++){
          var ftxt=followUps[fj].replace(/<[^>]+>/g,'').replace(/^[-•→▶]\s*/,'');
          var ftxtAttr=ftxt.replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;');
          out.push('<button class="sn-hint sn-inline-hint" onclick="_snSelectOption(this,\''+ftxtAttr+'\')">'+_snEscapeHtml(ftxt)+'</button>');
        }
        out.push('</div>');
      }
      i=lines.length;continue}
    // Question block
    if(/💬/.test(ln)){continue}

    // Section title detection
    if(_isSectionTitle(ln)){
      flushBuf();closeAllLists();closeBlock();
      var cls=_secCls(ln);
      out.push('<div class="sn-section-title'+cls+'">'+ln.trim()+'</div>');
      if(/sn-conclusion/.test(cls)){out.push('<div class="sn-recommend-block">');inBlock=true}
      continue;
    }

    // List items
    var ulMatch=ln.match(/^(\s*)([-•\*])\s+(.*)/);
    var olMatch=!ulMatch?ln.match(/^(\s*)\d+[\.\)]\s+(.*)/):null;

    if(ulMatch||olMatch){
      flushBuf();
      var indent=ulMatch?ulMatch[1].length:olMatch[1].length;
      var content=ulMatch?ulMatch[3]:olMatch[2];
      var lt=ulMatch?'ul':'ol';
      var targetDepth=indent<2?1:indent<4?2:3;
      if(listStack.length===0){out.push('<'+lt+'>');listStack.push({type:lt,indent:indent})}
      else if(targetDepth>listStack.length){out.push('<'+lt+'>');listStack.push({type:lt,indent:indent})}
      else if(targetDepth<listStack.length){closeLists(targetDepth)}

      // Pipe-separated data → card
      var pipeCount=(content.match(/\|/g)||[]).length;
      if(pipeCount>=2){
        var tsM=content.match(/^(.+?)\s*[—–]\s*(.*)/);
        var ts='',dataStr=content;
        if(tsM){ts=tsM[1];dataStr=tsM[2]}
        var parts=dataStr.split('|').map(function(p){return p.trim()}).filter(function(p){return p});
        var html='<li class="sn-data-row">';
        if(ts)html+='<div class="sn-data-ts">'+ts+'</div>';
        html+='<div class="sn-data-grid">';
        for(var pi=0;pi<parts.length;pi++){
          var pkv=parts[pi].match(/^(.+?):\s*(.+)$/);
          if(pkv)html+='<div class="sn-data-cell"><span class="sn-data-label">'+pkv[1].trim()+'</span><span class="sn-data-val">'+pkv[2].trim()+'</span></div>';
          else html+='<div class="sn-data-cell"><span class="sn-data-val">'+parts[pi]+'</span></div>';
        }
        html+='</div></li>';
        out.push(html);
      } else {
        out.push('<li>'+content+'</li>');
      }
      continue;
    }

    closeAllLists();
    if(ln.trim()===''){flushBuf();continue}
    // First line with emoji = status
    if(out.length===0&&buf.length===0&&/^[^\w\s<&]/.test(ln.trim())){out.push('<div class="sn-status-line">'+ln+'</div>');continue}
    // key:value pairs (but not URLs, not → lines, not too long values)
    var kvMatch=ln.match(/^([^:]{2,35}):\s+(.+)$/);
    if(kvMatch&&!/^(http|ftp)/i.test(kvMatch[2])&&kvMatch[2].length<120&&!/^→/.test(ln.trim())){
      flushBuf();
      out.push('<div class="sn-kv"><span class="sn-kv-k">'+kvMatch[1].trim()+'</span><span class="sn-kv-v">'+kvMatch[2].trim()+'</span></div>');
      continue;
    }
    // Standalone → lines outside reasoning block — render as plain text
    if(/^→/.test(ln.trim())){buf.push(ln);continue}
    buf.push(ln);
  }
  flushBuf();closeAllLists();closeTable();closeBlock();closeReasoning();
  var html=out.join('');
  // status emojis
  html=html.replace(/✅/g,'<span class="sn-good">✅</span>');
  html=html.replace(/🔴/g,'<span class="sn-bad">🔴</span>');
  html=html.replace(/❌/g,'<span class="sn-bad">❌</span>');
  html=html.replace(/⚠️/g,'<span class="sn-warn">⚠️</span>');
  html=html.replace(/🟡/g,'<span class="sn-warn">🟡</span>');
  return html;
}

function _snShowTyping(){
  var msgs=$('sanekMessages');
  var div=document.createElement('div');
  div.className='sn-typing';div.id='snTyping';
  div.innerHTML='<span></span><span></span><span></span>';
  msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;
}
function _snHideTyping(){var t=$('snTyping');if(t)t.remove()}

function _snShowActions(actions){
  if(!actions||!actions.length)return;
  var msgs=$('sanekMessages'),wrap=document.createElement('div');
  wrap.style.cssText='display:flex;flex-wrap:wrap;gap:4px;padding:0 4px;align-self:flex-start';
  actions.forEach(function(a){var badge=document.createElement('span');badge.className='sn-action';badge.textContent='✅ '+a.tool;wrap.appendChild(badge)});
  msgs.appendChild(wrap);msgs.scrollTop=msgs.scrollHeight;
}

function _snShowPending(pending){
  if(!pending)return;
  var msgs=$('sanekMessages'),div=document.createElement('div');
  div.className='sn-pending';
  div.innerHTML='<div style="font-size:13px;line-height:1.5">'+_snFormatText(pending.description)+'</div><div class="sn-pending-btns"><button class="sn-yes" onclick="sanekConfirm(true)">✅ Да, выполнить</button><button class="sn-no" onclick="sanekConfirm(false)">❌ Отмена</button></div>';
  msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;
  snSetState('alert');
}

function _snShowClarification(data){
  if(!data||!data.options||!data.options.length)return;
  var msgs=$('sanekMessages'),div=document.createElement('div');
  div.className='sanek-clarification-widget';
  var q=data.question||'Уточните запрос:';
  var btns=data.options.map(function(opt){
    var optAttr=opt.replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;');
    return '<button class="sanek-option-btn" onclick="_snSelectOption(this,\''+optAttr+'\')">'+_snEscapeHtml(opt)+'</button>';
  }).join('');
  div.innerHTML='<div class="sanek-clarification-options">'+btns+'</div>';
  msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;
}

function _snEscapeHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function _snFeedback(btn,rating){
  var fb=btn.closest('.sn-feedback');
  if(!fb)return;
  var comment=null;
  if(rating==='down'){comment=prompt('Что не так с ответом?')||null}
  fb.innerHTML='<span class="fb-done">'+(rating==='up'?'👍 Спасибо!':'👎 Учтём!')+'</span>';
  fetch('/api/ai/feedback',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({session_id:G._snSid,message_index:G._snMsgCount,rating:rating,comment:comment})
  }).catch(function(){});
}

function _snSelectOption(btn,selected){
  if(btn.disabled)return;
  // If already sending — force-reset and allow new request (previous may have timed out)
  if(G._snSending){G._snSending=false;if(_snAbort){try{_snAbort.abort()}catch(e){}}_snHideStopBtn();$('sanekSendBtn').disabled=false}
  // Disable ALL interactive buttons in chat (both types)
  document.querySelectorAll('.sanek-option-btn:not(:disabled)').forEach(function(b){b.disabled=true;b.style.opacity='.4'});
  document.querySelectorAll('.sn-inline-hint:not(:disabled)').forEach(function(b){b.disabled=true;b.style.opacity='.4'});
  btn.classList.add('selected');btn.style.opacity='1';
  _snAddMsg('user',selected);
  _snSendMessage(selected);
}

async function sanekConfirm(yes){
  document.querySelectorAll('.sn-pending').forEach(function(el){el.querySelectorAll('button').forEach(function(b){b.disabled=true})});
  var text=yes?'Да':'Нет';
  _snAddMsg('user',text);
  await _snSendMessage(text);
}

async function sendToSanek(){
  var input=$('sanekInput'),text=input.value.trim();
  if(!text)return;
  if(G._snSending){
    // Visual feedback: flash input border red briefly
    input.style.borderColor='#ef4444';
    setTimeout(function(){input.style.borderColor=''},800);
    return;
  }
  input.value='';
  _snAddMsg('user',text);
  await _snSendMessage(text);
}

function _snIsErrorMsg(msg){
  if(!msg)return false;
  // Only real error patterns — short messages starting with error emoji
  // Normal Sanek answers can start with ⚡📋🔧⚠ — those are NOT errors
  if(msg.length>300)return false;
  var errorPatterns=[
    /^⚠\s*(Лимит|Claude|GPT|API|Timeout|Ошибка|Sandbox|Модель)/i,
    /^🔑\s*(API|ключ|key|token|провайдер)/i,
    /^⏱\s*(Claude|GPT|Timeout|не ответил)/i,
    /^❌/
  ];
  return errorPatterns.some(function(p){return p.test(msg)});
}

function _snShowStopBtn(){
  var s=$('sanekSendBtn');s.style.display='none';
  var b=document.createElement('button');b.className='sn-stop-btn';b.id='snStopBtn';b.title='Остановить';
  b.innerHTML='<svg width="14" height="14" viewBox="0 0 14 14"><rect width="14" height="14" rx="2" fill="white"/></svg>';
  b.onclick=function(){if(_snAbort)_snAbort.abort()};
  s.parentNode.insertBefore(b,s.nextSibling);
}
function _snHideStopBtn(){
  var b=$('snStopBtn');if(b)b.remove();
  $('sanekSendBtn').style.display='';$('sanekSendBtn').disabled=false;
}

var _snToolLabels={
  'get_system_summary':'Сводка системы','get_devices':'Устройства','get_metrics':'Метрики',
  'get_alarms':'Проверяю аварии','get_alarm_history':'История аварий',
  'analyze_incident':'Анализ инцидента','get_economics_report':'Экономика',
  'search_knowledge':'Ищу в базе знаний','get_maintenance':'ТО записи',
  'get_maintenance_status':'Статус ТО','send_command':'Команда','set_power_limit':'Мощность',
  'get_history':'Загружаю историю','get_events':'События',
  'get_energy_report':'Считаю энергию','get_equipment_context':'Контекст оборудования','get_full_report':'📊 Полный отчёт (энергия+экономика+инциденты)',
  'query_data':'Выполняю SQL-запрос','get_action_effectiveness':'Эффективность действий',
  'execute_code':'\u23f3 Генерирую файл (~15-20 сек)...',
  'get_code_context':'Готовлю контекст','propose_action':'Предлагаю действие',
  'execute_action':'Выполняю действие','remember':'Запоминаю','recall':'Вспоминаю',
  'get_current_metrics':'📡 Читаю метрики','get_metrics_history':'📈 История метрик',
  'get_topology':'🏭 Структура системы','get_alarm_reference':'📋 Справочник алармов',
  'query_db':'🔍 SQL-запрос','save_sop_entry':'💾 Сохраняю SOP',
  'get_bitrix_tasks':'📋 Задачи Bitrix24','create_bitrix_task':'➕ Создаю задачу',
  'read_modbus_register':'🔧 Читаю регистр Modbus','send_modbus_command':'⚡ Команда Modbus',
  'run_python_code':'🐍 Выполняю Python код',
  'get_economics_report':'💰 Экономика (себестоимость)',
  'get_db_schema':'📂 Структура базы данных'
};
function _snToolLabel(n,desc){return desc||_snToolLabels[n]||n}

async function _snSendMessage(text){
  if(!_snHealthOk){
    _snAddMsg('error','⚠ '+_snHealthError+'\n\nОткройте «🤖 AI Провайдер» в боковом меню и настройте провайдера.');
    snSetState('alert');
    return;
  }
  G._snSending=true;$('sanekSendBtn').disabled=true;
  snSetState('thinking');
  // Disable all interactive buttons (welcome hints, clarification, pending, inline hints)
  document.querySelectorAll('.sn-hint:not(:disabled)').forEach(function(b){b.disabled=true;b.style.opacity='.4';b.style.pointerEvents='none'});
  document.querySelectorAll('.sanek-option-btn:not(:disabled)').forEach(function(b){b.disabled=true;b.style.opacity='.4'});
  document.querySelectorAll('.sn-pending-btns button:not(:disabled)').forEach(function(b){b.disabled=true;b.style.opacity='.4'});
  _snShowTyping();
  _snAbort=new AbortController();
  _snShowStopBtn();
  var progressEl=null,mode='';

  try{
    var body={message:text};
    if(G._snSid)body.session_id=G._snSid;
    var ctx=_snGetContext();
    if(ctx.site)body.context={site:ctx.site,site_name:ctx.siteName,view:ctx.view};
    G._snMsgCount++;_snUpdateCounter();

    var resp=await fetch(API_BASE+'/api/ai/chat/stream',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),signal:_snAbort.signal
    });
    if(!resp.ok)throw new Error('POST /api/ai/chat/stream: '+resp.status);

    var reader=resp.body.getReader(),decoder=new TextDecoder(),buf='';
    while(true){
      var chunk=await reader.read();
      if(chunk.done)break;
      buf+=decoder.decode(chunk.value,{stream:true});
      var parts=buf.split('\n\n');buf=parts.pop();
      for(var i=0;i<parts.length;i++){
        var ln=parts[i].trim();
        if(!ln.startsWith('data: '))continue;
        var ev;try{ev=JSON.parse(ln.slice(6))}catch(x){continue}

        if(ev.type==='mode'){
          mode=ev.mode;_snHideTyping();
          var msgs=$('sanekMessages'),badge=document.createElement('div');
          badge.className='sn-mode '+(mode==='deep'?'deep':'fast');
          badge.textContent=mode==='deep'?'🔬 Глубокий анализ':'⚡ Быстрый ответ';
          msgs.appendChild(badge);msgs.scrollTop=msgs.scrollHeight;
          if(mode==='deep')_snShowTyping();
        }
        else if(ev.type==='thinking'){
          _snHideTyping();
          // Remove previous thinking indicator + timer
          var oldTh=document.querySelector('.sn-thinking');if(oldTh)oldTh.remove();
          if(window._snThinkTimer)clearInterval(window._snThinkTimer);
          var thDiv=document.createElement('div');thDiv.className='sn-thinking';thDiv.id='snThinking';
          var thText=ev.step==='analyzing_query'?'🧠 Анализирую запрос':'🧠 Формирую ответ';
          var thDetail=ev.detail?' · <span style="opacity:.7">'+ev.detail+'</span>':'';
          thDiv.innerHTML='<span class="sn-spin"></span> <span class="sn-think-text">'+thText+'</span>'+thDetail+'<span class="sn-think-timer" id="snThinkTime">0с</span>';
          $('sanekMessages').appendChild(thDiv);$('sanekMessages').scrollTop=$('sanekMessages').scrollHeight;
          var _thStart=Date.now();
          window._snThinkTimer=setInterval(function(){
            var el=$('snThinkTime');if(el)el.textContent=Math.round((Date.now()-_thStart)/1000)+'с';
          },1000);
        }
        else if(ev.type==='step'){
          _snHideTyping();
          // Remove thinking indicator + timer when tools start
          if(window._snThinkTimer){clearInterval(window._snThinkTimer);window._snThinkTimer=null}
          var thEl=document.querySelector('.sn-thinking');if(thEl)thEl.remove();
          if(!progressEl){progressEl=document.createElement('div');progressEl.className='sn-progress';$('sanekMessages').appendChild(progressEl)}
          var tl=_snToolLabel(ev.tool,ev.description);
          if(ev.status==='running'){
            var step=document.createElement('div');step.className='sn-step';step.setAttribute('data-tool',ev.tool);
            step.innerHTML='<span class="sn-spin"></span> '+tl;progressEl.appendChild(step);
            // Prominent ETA banner with countdown + progress bar
            if(ev.tool==='execute_code'){
              var eta=document.createElement('div');eta.className='sn-eta-banner';eta.id='snEtaBanner';
              eta.innerHTML='<div class="sn-eta-top"><span class="sn-eta-icon">📄</span> Генерация документа... <span class="sn-eta-countdown" id="snEtaCount">~20 сек</span></div><div class="sn-eta-bar"><div class="sn-eta-fill" id="snEtaFill"></div></div>';
              $('sanekMessages').appendChild(eta);
              // Start countdown
              var _etaTotal=20,_etaLeft=20;
              window._snEtaTimer=setInterval(function(){
                _etaLeft--;
                var pct=Math.min(100,Math.round(((_etaTotal-_etaLeft)/_etaTotal)*100));
                var el=$('snEtaCount'),bar=$('snEtaFill');
                if(el)el.textContent=_etaLeft>0?'~'+_etaLeft+' сек':'почти готово...';
                if(bar)bar.style.width=pct+'%';
                if(_etaLeft<=0)clearInterval(window._snEtaTimer);
              },1000);
            }
            $('sanekMessages').scrollTop=$('sanekMessages').scrollHeight;
          }else if(ev.status==='done'){
            var pending=progressEl.querySelectorAll('.sn-step:not(.done)[data-tool="'+ev.tool+'"]');
            if(pending.length){var last=pending[pending.length-1];last.className='sn-step done';last.innerHTML='✅ '+_snToolLabel(ev.tool)}
            // Remove ETA banner when execute_code completes
            if(ev.tool==='execute_code'){
              if(window._snEtaTimer)clearInterval(window._snEtaTimer);
              var eb=$('snEtaBanner');if(eb){eb.classList.add('done');setTimeout(function(){eb.remove()},1500)}
            }
          }
          $('sanekMessages').scrollTop=$('sanekMessages').scrollHeight;
          _snShowTyping();
        }
        else if(ev.type==='text_delta'){
          // Real-time text streaming — append to streaming bubble
          _snHideTyping();
          if(window._snThinkTimer){clearInterval(window._snThinkTimer);window._snThinkTimer=null}
          var thRm=document.querySelector('.sn-thinking');if(thRm)thRm.remove();
          if(!window._snStreamBubble){
            window._snStreamText='';
            var m=document.createElement('div');m.className='sn-msg assistant';
            m.innerHTML='<div class="sn-bubble sn-stream-bubble"></div>';
            $('sanekMessages').appendChild(m);
            window._snStreamBubble=m.querySelector('.sn-stream-bubble');
          }
          window._snStreamText+=ev.text;
          window._snStreamBubble.innerHTML=_snFormatText(window._snStreamText);
          $('sanekMessages').scrollTop=$('sanekMessages').scrollHeight;
        }
        else if(ev.type==='done'){
          _snHideTyping();
          if(window._snThinkTimer){clearInterval(window._snThinkTimer);window._snThinkTimer=null}
          var thEl2=document.querySelector('.sn-thinking');if(thEl2)thEl2.remove();
          if(ev.session_id)G._snSid=ev.session_id;
          G._snMsgCount++;_snUpdateCounter();
          // If we were streaming text, replace bubble with final formatted version
          if(window._snStreamBubble){
            var streamParent=window._snStreamBubble.closest('.sn-msg');
            if(streamParent)streamParent.remove();
            window._snStreamBubble=null;window._snStreamText='';
          }
          if(mode==='fast'&&ev.actions&&ev.actions.length)_snShowActions(ev.actions);
          if(ev.message){
            if(_snIsErrorMsg(ev.message)){
              _snAddMsg('error',ev.message);
              snSetState('alert');setTimeout(function(){if(_sn.state==='alert')snSetState('idle')},5000);
            }else{
              if(ev.message)_snAddMsg('assistant',ev.message);
              if(ev.clarification){var _lm=document.querySelector(".sn-msg.assistant:last-child");if(_lm){var _sq=_lm.querySelectorAll(".sn-question");_sq.forEach(function(e){e.remove()})}_snShowClarification(ev.clarification);}
              else if(ev.pending_action)_snShowPending(ev.pending_action);
              else{snSetState('success');setTimeout(function(){if(_sn.state==='success')snSetState('idle')},2500)}
            }
          }else if(ev.pending_action){_snShowPending(ev.pending_action)}
          else if(ev.clarification){_snShowClarification(ev.clarification)}else{_snAddMsg('error','❌ Пустой ответ от сервера.');snSetState('alert');setTimeout(function(){if(_sn.state==='alert')snSetState('idle')},5000)}
        }
        else if(ev.type==='error'){
          _snHideTyping();
          if(window._snThinkTimer){clearInterval(window._snThinkTimer);window._snThinkTimer=null}
          var thEl3=document.querySelector('.sn-thinking');if(thEl3)thEl3.remove();
          if(ev.session_id)G._snSid=ev.session_id;
          _snAddMsg('error','❌ '+ev.message);
          snSetState('alert');setTimeout(function(){if(_sn.state==='alert')snSetState('idle')},5000);
        }
      }
    }
  }catch(e){
    _snHideTyping();
    if(e.name==='AbortError'){
      _snAddMsg('assistant','⏹ Запрос остановлен.');
      snSetState('idle');_snAbort=null;_snHideStopBtn();G._snSending=false;return;
    }
    var em=e.message||'',msg;
    if(em.includes('404'))msg='❌ Эндпоинт чата не найден (404).\n\nБэкенд СКАДА требует обновления.';
    else if(em.includes('Failed to fetch')||em.includes(': 0'))msg='❌ Сервер СКАДА недоступен.';
    else if(em.includes('500'))msg='❌ Внутренняя ошибка сервера.\n\nПроверьте логи: docker logs scada-backend';
    else if(em.includes('502')||em.includes('503'))msg='❌ Сервер временно недоступен.\n\nПодождите 10 секунд.';
    else msg='❌ Ошибка: '+(em||'проверьте доступность бэкенда.');
    _snAddMsg('error',msg);
    snSetState('alert');setTimeout(function(){if(_sn.state==='alert')snSetState('idle')},5000);
  }finally{
    _snAbort=null;_snHideStopBtn();
    G._snSending=false;$('sanekSendBtn').disabled=false;
    // Re-enable welcome hints if still visible (e.g. after error before welcome removed)
    document.querySelectorAll('.sn-hint:disabled').forEach(function(b){b.disabled=false;b.style.opacity='';b.style.pointerEvents=''});
  }
}

// === MESSAGE COUNTER ===
function _snUpdateCounter(){
  var el=$('snMsgCounter');if(!el)return;
  if(G._snMsgCount<1){el.classList.remove('vis','warn','crit');return}
  el.textContent=G._snMsgCount+' сбщ';
  el.classList.add('vis');
  el.classList.toggle('warn',G._snMsgCount>=30&&G._snMsgCount<45);
  el.classList.toggle('crit',G._snMsgCount>=45);
}

// === PAGE CONTEXT BADGE ===
function _snGetContext(){
  var ctx={site:null,siteName:null,view:null};
  if(typeof G.cur!=='undefined'&&G.cur&&typeof G.S!=='undefined'&&G.S[G.cur]){
    ctx.site=G.cur;ctx.siteName=G.S[G.cur].name;
  }
  if(typeof G.curView!=='undefined'&&G.curView){ctx.view=G.curView}
  return ctx;
}

function _snUpdateCtxBadge(){
  var el=$('snCtxBadge');if(!el)return;
  var ctx=_snGetContext();
  if(!ctx.siteName){el.style.display='none';return}
  var viewLabel={'monitoring':'Мониторинг','alarms':'Аварии','archive':'Архив','to':'ТО'}[ctx.view]||'';
  el.textContent=ctx.siteName+(viewLabel?' · '+viewLabel:'');
  el.style.display='inline-block';
}

// === HISTORY PANEL ===
function _snToggleHistory(){
  G._snHistOpen=!G._snHistOpen;
  var panel=$('snHistPanel'),btn=$('snHistBtn');
  if(panel)panel.classList.toggle('open',G._snHistOpen);
  if(btn)btn.classList.toggle('active',G._snHistOpen);
  if(G._snHistOpen)_snLoadSessions();
}

async function _snLoadSessions(){
  var list=$('snHistList');if(!list)return;
  list.innerHTML='<div class="sn-hist-empty">Загрузка...</div>';
  try{
    var r=await api.get('/api/ai/chat/sessions?limit=30');
    if(!r.sessions||!r.sessions.length){
      list.innerHTML='<div class="sn-hist-empty">Нет сохранённых чатов</div>';
      return;
    }
    var html='';
    for(var i=0;i<r.sessions.length;i++){
      var s=r.sessions[i];
      var isActive=G._snSid&&s.session_id===G._snSid;
      var dt=s.last_at?_snFmtDate(s.last_at):'';
      var preview=s.first_message||('Сессия '+s.session_id);
      html+='<div class="sn-hist-item'+(isActive?' active':'')+'" onclick="_snLoadSession(\''+s.session_id+'\')">'
        +'<div class="sn-hi-icon">'+(isActive?'💬':'🗨')+'</div>'
        +'<div class="sn-hi-body">'
        +'<div class="sn-hi-title">'+_snEsc(preview)+'</div>'
        +'<div class="sn-hi-meta"><span>'+dt+'</span><span>'+s.message_count+' сбщ</span></div>'
        +'</div>'
        +'<button class="sn-hi-del" onclick="event.stopPropagation();_snDeleteSession(\''+s.session_id+'\')" title="Удалить чат">🗑</button>'
        +'</div>';
    }
    list.innerHTML=html;
  }catch(e){
    list.innerHTML='<div class="sn-hist-empty">Ошибка загрузки: '+(e.message||'')+'</div>';
  }
}

function _snFmtDate(iso){
  try{
    var d=new Date(iso);
    var now=new Date();
    var hh=String(d.getHours()).padStart(2,'0');
    var mm=String(d.getMinutes()).padStart(2,'0');
    var isToday=d.toDateString()===now.toDateString();
    if(isToday)return 'Сегодня '+hh+':'+mm;
    var yesterday=new Date(now);yesterday.setDate(yesterday.getDate()-1);
    if(d.toDateString()===yesterday.toDateString())return 'Вчера '+hh+':'+mm;
    var dd=String(d.getDate()).padStart(2,'0');
    var mo=String(d.getMonth()+1).padStart(2,'0');
    return dd+'.'+mo+' '+hh+':'+mm;
  }catch(e){return iso}
}

function _snEsc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

async function _snLoadSession(sid){
  if(sid===G._snSid){_snToggleHistory();return}
  G._snSid=sid;G._snMsgCount=0;
  if(G._snHistOpen)_snToggleHistory();
  var msgs=$('sanekMessages');
  var welcome=msgs.querySelector('.sn-welcome');if(welcome)welcome.remove();
  msgs.innerHTML='<div class="sn-hist-empty">Загрузка истории...</div>';
  snSetState('thinking');
  try{
    var r=await api.get('/api/ai/chat/history?session_id='+sid+'&limit=100');
    msgs.innerHTML='';
    if(r.messages&&r.messages.length){
      for(var i=0;i<r.messages.length;i++){
        var m=r.messages[i];
        if(m.role==='user'||m.role==='assistant'||m.role==='error'){
          _snAddMsg(m.role==='error'?'error':m.role,m.content);
          G._snMsgCount++;
        }
      }
    }else{
      msgs.innerHTML='<div class="sn-hist-empty">Пустая сессия</div>';
    }
    _snUpdateCounter();
    snSetState('idle');
  }catch(e){
    msgs.innerHTML='';
    _snAddMsg('error','Не удалось загрузить историю: '+(e.message||''));
    snSetState('alert');
  }
}

async function _snDeleteSession(sid){
  if(!confirm('Удалить этот чат?'))return;
  try{
    await api.del('/api/ai/chat/sessions/'+sid);
    // If deleted session is current — reset to new chat
    if(G._snSid===sid)sanekNewSession();
    _snLoadSessions();
  }catch(e){
    alert('Ошибка удаления: '+(e.message||''));
  }
}

// === HEALTH CHECK — периодическая проверка AI-провайдера ===
var _snHealthOk=true,_snHealthError='',_snHealthTipOpen=false;

function _snShowHealthDetail(){
  var row=$('snStatusRow');if(!row)return;
  // Закрыть если уже открыт
  var existing=row.querySelector('.sn-health-tip');
  if(existing){existing.remove();_snHealthTipOpen=false;return}
  if(_snHealthOk)return; // Не показывать если всё ок
  var tip=document.createElement('div');
  tip.className='sn-health-tip';
  tip.innerHTML='<button class="sn-tip-close" onclick="event.stopPropagation();this.parentElement.remove()">&times;</button>'
    +'<b>⚠ Проблема:</b> '+(_snHealthError||'Неизвестная ошибка')
    +'<br><br>Откройте <b>«🤖 AI Провайдер»</b> в боковом меню, добавьте API-ключ и активируйте провайдера.';
  row.appendChild(tip);
  _snHealthTipOpen=true;
  // Автозакрытие через 10 сек
  setTimeout(function(){if(tip.parentElement)tip.remove();_snHealthTipOpen=false},10000);
}

async function _snHealthCheck(){
  if(G._snSending)return;
  try{
    var r=await api.get('/api/ai/health');
    if(r.available){
      _snHealthOk=true;_snHealthError='';
      if(_sn.state==='alert'||_sn.state==='sleeping')snSetState('idle');
    }else{
      _snHealthOk=false;
      _snHealthError=r.error||'AI провайдер недоступен';
      if(_sn.state==='idle'||_sn.state==='sleeping')snSetState('alert');
    }
  }catch(e){
    _snHealthOk=false;
    _snHealthError='Сервер СКАДА недоступен';
    if(_sn.state==='idle'||_sn.state==='sleeping')snSetState('alert');
  }
}

setTimeout(_snHealthCheck,2000);
setInterval(_snHealthCheck,30000);
setTimeout(_snUpdateCtxBadge,500);

// === EXPORTS ===
export {
  toggleSanek,
  sendToSanek,
  sanekHint,
  sanekNewSession,
  sanekConfirm,
  _snFeedback,
  _snLoadSession,
  _snSelectOption,
  _snShowHealthDetail,
  _snToggleHistory,
  _snUpdateThemeColors,
  _snInitTypingDetection,
  _snDeleteSession,
  _snUpdateCtxBadge,
  snSetState,
  _snFormatText
};
