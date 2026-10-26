# mqttBridge: add-on che inoltra i dati di Home Assistant così come sono, senza logica

Serviva un modo "il più lineare possibile" per mandare a microBees tutti i dispositivi e le entità di Home Assistant e
i loro aggiornamenti, con dati di connessione e topic nella configurazione, verso **consumer nuovi** (non BnBees).
Abbiamo scelto un **add-on** (container a parte, Python) che legge registri, stati ed eventi tramite l'**API WebSocket
del Supervisor** e li pubblica con paho-mqtt, invece di estendere l'integrazione custom `bnbees_integration`: l'add-on si
installa e si configura dall'interfaccia e non tocca il processo di Home Assistant. Federico ha deciso che l'add-on
**non fa logica**: prende i dati e li invia, senza calcoli né condizioni sui valori. Quindi: all'avvio un `new_device` per
ogni dispositivo (`dict_repr` + `extended_dict` delle entità + stato grezzo), poi ogni evento di registro o di stato
diventa un messaggio con l'evento com'è e l'elemento com'è ora; le entità senza dispositivo partono all'avvio come
`new_entity` e poi seguono gli stessi eventi. QoS 0 (il broker non conferma la consegna).
Scartati: le attese per raggruppare le modifiche, i messaggi riassuntivi (`device_updated`) e i campi calcolati
dell'integrazione (`available`, `domain`, `relay_value`, `is_on`). Conseguenze: il consumer ricompone i dispositivi
nuovi dagli eventi e ricava i valori derivati; il volume di messaggi segue quello degli eventi di Home Assistant.
Fuori da questa versione: comandi in ingresso e TLS/certificati per RabbitMQ (con Antonio).
