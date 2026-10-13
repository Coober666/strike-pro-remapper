export const EXERCISES={
  soft:{name:'Soft hits',prompt:'On one pad, play 20 separate soft hits at a comfortable, steady pace. Stop, name the pad and note anything you noticed.'},
  hard:{name:'Hard hits',prompt:'On the same pad, play 20 separate firm hits at a comfortable, steady pace. Use your normal playing technique. Stop and note the pad and any settings changed.'},
  rolls:{name:'Rolls',prompt:'On one pad, play a comfortable roll for about 10 seconds. Stop and note the sticking, approximate pace and any settings changed. Short gaps alone do not identify double triggers.'},
  hihat:{name:'Hi-hat movement',prompt:'Slowly move the hi-hat pedal from open to closed and back five times, then play several bow hits at each position. Stop and inspect notes and the full-take controller list. Controller meanings depend on the module.'}
};
export function sessionTags(value=[]) {
  if (!Array.isArray(value) || value.length > 12 || value.some(t => typeof t !== 'string' || !t.trim() || t.length > 32 || /[,\r\n\t]/.test(t))) throw new Error('Use up to 12 tags, each 1–32 characters without commas or line breaks.');
  return [...new Set(value.map(t => t.trim().toLowerCase()))];
}
export function matchesSearch(item, query) {
  const text=[item.name,item.source,item.notesText,...(item.tags || [])].filter(Boolean).join(' ').toLowerCase();
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean).every(word => text.includes(word));
}
