#include <CoreFoundation/CoreFoundation.h>
#include <CoreMIDI/CoreMIDI.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>

typedef void *SpyClient;
typedef void *SpyPort;
static OSStatus (*spyConnect)(SpyPort,MIDIEndpointRef,void*);
static SpyPort spyPort;
static MIDIPortRef inputPort;
static MIDIEndpointRef inputs[256],outputs[256];
static int ni,no;
static double now(void) { struct timespec t; clock_gettime(CLOCK_REALTIME,&t); return t.tv_sec+t.tv_nsec/1e9; }
static void name(MIDIEndpointRef e,char *s,size_t n) {
 CFStringRef v=NULL; s[0]=0;
 if(!MIDIObjectGetStringProperty(e,kMIDIPropertyDisplayName,&v)&&v) { CFStringGetCString(v,s,n,kCFStringEncodingUTF8); CFRelease(v); }
}
static void packets(const MIDIPacketList *list,const char *direction,void *ctx) {
 char s[512]; name((MIDIEndpointRef)(uintptr_t)ctx,s,sizeof(s));
 const MIDIPacket *p=&list->packet[0];
 for(UInt32 i=0;i<list->numPackets;i++) {
  printf("%.6f %s endpoint=%u name=[%s] host_ticks=%llu bytes=%u hex=",now(),direction,(unsigned)(uintptr_t)ctx,s,p->timeStamp,p->length);
  for(unsigned j=0;j<p->length;j++) printf("%02X",p->data[j]);
  puts(""); p=MIDIPacketNext(p);
 }
}
static void readInput(const MIDIPacketList *l,void *a,void *b) { packets(l,"FROM_STRIKE",b); }
static void scan(void) {
 for(int dir=0;dir<2;dir++) {
  ItemCount count=dir?MIDIGetNumberOfDestinations():MIDIGetNumberOfSources();
  for(ItemCount i=0;i<count;i++) {
   MIDIEndpointRef e=dir?MIDIGetDestination(i):MIDIGetSource(i); char s[512]; name(e,s,sizeof(s));
   if(!strcasestr(s,"strike")) continue;
   MIDIEndpointRef *seen=dir?outputs:inputs; int *n=dir?&no:&ni; int known=0;
   for(int j=0;j<*n;j++) if(seen[j]==e) known=1;
   if(known) continue;
   OSStatus err=dir?spyConnect(spyPort,e,(void*)(uintptr_t)e):MIDIPortConnectSource(inputPort,e,(void*)(uintptr_t)e);
   printf("%.6f ATTACH %s endpoint=%u name=[%s] status=%d\n",now(),dir?"SPY_DESTINATION":"SOURCE",e,s,(int)err);
   if(!err&&*n<256) seen[(*n)++]=e;
  }
 }
}
int main(int argc,char **argv) {
 setbuf(stdout,NULL);
 void *lib=dlopen("/Applications/MIDI Monitor.app/Contents/Frameworks/SnoizeMIDISpy.framework/SnoizeMIDISpy",RTLD_NOW);
 if(!lib) { fprintf(stderr,"%s\n",dlerror()); return 1; }
 OSStatus (*create)(SpyClient*)=dlsym(lib,"MIDISpyClientCreate");
 OSStatus (*portCreate)(SpyClient,MIDIReadBlock,SpyPort*)=dlsym(lib,"MIDISpyPortCreate");
 OSStatus (*dispose)(SpyClient)=dlsym(lib,"MIDISpyClientDispose");
 spyConnect=dlsym(lib,"MIDISpyPortConnectDestination");
 if(!create||!portCreate||!dispose||!spyConnect) return 2;
 MIDIClientRef midi; SpyClient spy;
 OSStatus err=MIDIClientCreate(CFSTR("Strike passive evidence capture"),NULL,NULL,&midi);
 printf("%.6f MIDI_CLIENT status=%d\n",now(),(int)err); if(err) return 3;
 err=MIDIInputPortCreate(midi,CFSTR("Strike passive input"),readInput,NULL,&inputPort);
 printf("%.6f INPUT_PORT status=%d\n",now(),(int)err); if(err) return 4;
 err=create(&spy); printf("%.6f SPY_CLIENT status=%d\n",now(),(int)err); if(err) return 5;
 err=portCreate(spy,^(const MIDIPacketList *l,void *ctx){ packets(l,"TO_STRIKE",ctx); },&spyPort);
 printf("%.6f SPY_PORT status=%d\n",now(),(int)err); if(err) return 6;
 double stop=now()+(argc>1?atoi(argv[1]):180);
 scan(); printf("%.6f READY sources=%d destinations=%d\n",now(),ni,no);
 while(now()<stop) { CFRunLoopRunInMode(kCFRunLoopDefaultMode,0.25,false); scan(); }
 dispose(spy); MIDIClientDispose(midi); printf("%.6f STOP\n",now()); return 0;
}
