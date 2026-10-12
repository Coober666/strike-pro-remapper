#include <CoreFoundation/CoreFoundation.h>
#include <CoreMIDI/CoreMIDI.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* Replays only the exact startup packet observed from the official editor. */
int main(void) {
 MIDIClientRef client; MIDIPortRef port; MIDIEndpointRef target=0; int count=0;
 OSStatus err=MIDIClientCreate(CFSTR("Strike approved initialization test"),NULL,NULL,&client);
 if(err) return 1;
 for(ItemCount i=0;i<MIDIGetNumberOfDestinations();i++) {
  MIDIEndpointRef ep=MIDIGetDestination(i); CFStringRef value=NULL; char name[512]={0};
  if(!MIDIObjectGetStringProperty(ep,kMIDIPropertyDisplayName,&value)&&value) {
   CFStringGetCString(value,name,sizeof(name),kCFStringEncodingUTF8); CFRelease(value);
  }
  if(!strcmp(name,"Alesis Strike")) { target=ep; count++; }
 }
 if(count!=1) { fprintf(stderr,"Expected exactly one Alesis Strike destination; found %d\n",count); MIDIClientDispose(client); return 2; }
 err=MIDIOutputPortCreate(client,CFSTR("Exact captured startup only"),&port);
 if(err) { MIDIClientDispose(client); return 3; }
 Byte bytes[]={0xF0,0x00,0x00,0x0E,0x48,0x0E,0x33,0x03,0x01,0xF7};
 MIDIPacketList list; MIDIPacket *p=MIDIPacketListInit(&list);
 if(!MIDIPacketListAdd(&list,sizeof(list),p,0,sizeof(bytes),bytes)) return 4;
 err=MIDISend(port,target,&list);
 printf("MIDISend endpoint=%u status=%d hex=F000000E480E330301F7\n",target,(int)err);
 usleep(300000); MIDIPortDispose(port); MIDIClientDispose(client); return err?5:0;
}
