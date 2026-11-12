// Original OMH helper, MIT. Checks cmap coverage, NOT shaping or native-language correctness.
// TTF/OTF sfnt only. WOFF/collections require explicit conversion by the host; never auto-download.
export function glyphChecker(data) {
  if(data.length<12||!['00010000','4f54544f'].includes(data.subarray(0,4).toString('hex')))throw Error('HOLD: glyph check requires TTF/OTF sfnt font');
  const tables=data.readUInt16BE(4);let offset=-1,length=0;
  for(let i=0;i<tables;i++){
    const at=12+i*16;if(at+16>data.length)throw Error('invalid font table');
    if(data.subarray(at,at+4).toString()==='cmap'){offset=data.readUInt32BE(at+8);length=data.readUInt32BE(at+12);}
  }
  if(offset<0||offset+length>data.length)throw Error('missing/invalid font cmap');
  const cmap=data.subarray(offset,offset+length),count=cmap.readUInt16BE(2),checks=[];
  for(let i=0;i<count;i++){
    const at=4+i*8,platform=cmap.readUInt16BE(at),encoding=cmap.readUInt16BE(at+2),sub=cmap.readUInt32BE(at+4);
    if(!(platform===0||platform===3&&[1,10].includes(encoding)))continue;
    const format=cmap.readUInt16BE(sub);
    if(format===12){
      const groups=cmap.readUInt32BE(sub+12);
      if(groups>100000||sub+16+groups*12>cmap.length)throw Error('invalid cmap12');
      checks.push(code=>{let lo=0,hi=groups-1;while(lo<=hi){const mid=(lo+hi)>>1,p=sub+16+mid*12,a=cmap.readUInt32BE(p),b=cmap.readUInt32BE(p+4);if(code<a)hi=mid-1;else if(code>b)lo=mid+1;else return cmap.readUInt32BE(p+8)+code-a!==0;}return false;});
    }else if(format===4){
      const segments=cmap.readUInt16BE(sub+6)/2,ends=sub+14,starts=ends+segments*2+2,deltas=starts+segments*2,offsets=deltas+segments*2;
      if(!Number.isInteger(segments)||offsets+segments*2>cmap.length)throw Error('invalid cmap4');
      checks.push(code=>{
        if(code>65535)return false;
        for(let j=0;j<segments;j++){
          const end=cmap.readUInt16BE(ends+2*j),start=cmap.readUInt16BE(starts+2*j);
          if(code>end)continue;if(code<start)return false;
          const delta=cmap.readInt16BE(deltas+2*j),range=cmap.readUInt16BE(offsets+2*j);
          if(!range)return ((code+delta)&65535)!==0;
          const p=offsets+2*j+range+2*(code-start);
          if(p+2>cmap.length)throw Error('cmap glyph offset out of range');
          const glyph=cmap.readUInt16BE(p);return glyph!==0&&((glyph+delta)&65535)!==0;
        }return false;
      });
    }
  }
  if(!checks.length)throw Error('HOLD: unsupported Unicode font cmap');
  return code=>checks.some(check=>check(code));
}

export function assertGlyphs(text,checks){
  for(const character of text){
    const code=character.codePointAt(0);
    if(/[\s]/u.test(character)||[0x200c,0x200d,0x2066,0x2067,0x2068,0x2069].includes(code))continue;
    if(!checks.some(check=>check(code)))throw Error('HOLD: missing glyph U+'+code.toString(16).toUpperCase());
  }
}
