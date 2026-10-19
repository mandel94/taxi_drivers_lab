'use strict';

const { getSite } = require('./wp-client');

(async () => {
  try {
    console.log('Inizio test di discovery del client WPAPI...');
    const site = await getSite();

    console.log('Discovery riuscita.');
    console.log('Metodi/collection disponibili sul client:');
    console.log(Object.keys(site).filter((k) => typeof site[k] === 'function').sort());

    console.log('\nProvo una richiesta reale: ultimi 3 post...');
    const posts = await site.posts().perPage(3).param('_fields', 'id,title,link,date');
    posts.forEach((p) => {
      console.log(`- [${p.id}] ${p.title.rendered} (${p.date}) -> ${p.link}`);
    });
  } catch (err) {
    console.error('Errore durante discovery o richiesta:', err.message);
    process.exit(1);
  }
})();
