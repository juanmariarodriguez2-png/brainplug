# Chrome Web Store submission

Copy the English or Spanish fields below into the listing. The extension itself
uses the browser language for its English/Spanish popup. Version comes from
`extension/manifest.json`.

Build the upload with `python scripts/package_extension.py`. The output is
`dist/brainplug-capture-VERSION.zip`, with `manifest.json` at the ZIP root.
Use `--output-dir PATH` to build elsewhere. Upload this ZIP in the developer
dashboard. Homepage: https://brainplug.app/.

Privacy policy URL: https://brainplug.app/privacy.html

Support: https://github.com/juanmariarodriguez2-png/brainplug/issues

## English listing

**Name:** Brainplug capture

**Short description:** Save the prompts you send to ChatGPT, Claude, Gemini, Copilot and Perplexity locally for Brainplug.

**Category:** Productivity → Tools

**Detailed description:**

Brainplug capture keeps a local copy of the prompts you send on ChatGPT, Claude,
Gemini, Microsoft Copilot and Perplexity, so you can add your writing to Brainplug.
It does not read or save the AI’s answers.

When you press Enter or click Send and the message box empties, the extension
saves your text in this browser’s local extension storage. Each record includes
the site, conversation identifier, available page title and timestamp. Messages
are limited to 20,000 characters per capture. Unsent drafts are not retained.

Open the popup to see how many messages are saved, pause or resume capture,
download a JSON file, or delete everything saved. Deletion asks for a second
click. Pausing keeps your existing history.

“Make my Brainplug” opens https://brainplug.app/app/. The web app offers to add
your saved messages. If you choose “Add them”, the extension passes them to the
page inside your browser, without a network transfer. The web app analyses them
in the tab to create your map. You can also import the downloaded JSON file into
Brainplug, including its Python version.

The extension makes no network requests and uploads no captures. There are no
Brainplug accounts, cookies, analytics or advertising. The AI sites still receive
the prompts you send to them under their own policies. Loading the Brainplug
website makes normal requests to its GitHub Pages host.

Supported sites: chatgpt.com, chat.openai.com, claude.ai, gemini.google.com,
copilot.microsoft.com and www.perplexity.ai. Capture depends on detecting a send
action and an emptied composer; changes to those sites may affect it. Automated
browser tests use stand-in pages, not the live services.

Brainplug is open source under the MIT licence. Privacy policy:
https://brainplug.app/privacy.html. Questions or bugs:
https://github.com/juanmariarodriguez2-png/brainplug/issues.

### Privacy practices — English

**Single purpose:** Keep a local copy of the prompts the user sends to supported
AI chat sites so the user can import their own writing into Brainplug.

**Permission justifications:**

| Permission | Justification |
| --- | --- |
| `storage` | Store sent prompts, conversation metadata and the capture pause setting in `chrome.storage.local`; read them for the popup, JSON export and local web-app import; delete saved captures on request. |
| `unlimitedStorage` | Keep a growing local prompt history beyond Chrome’s default `storage.local` quota, without uploading it or dropping older messages to meet that quota. Disk space still limits storage. |

**Host access justifications:** These are `content_scripts.matches`, not an
additional `host_permissions` list. Each match is needed for the single purpose.

| Match | Justification |
| --- | --- |
| `https://chatgpt.com/*` | Run the capture script in ChatGPT to detect sent composer text and retain conversation identifiers and titles. |
| `https://chat.openai.com/*` | Run the same capture script at ChatGPT’s older address when used. |
| `https://claude.ai/*` | Capture the user’s sent prompts and conversation metadata on Claude. |
| `https://gemini.google.com/*` | Capture the user’s sent prompts and conversation metadata on Gemini. |
| `https://copilot.microsoft.com/*` | Capture the user’s sent prompts and conversation metadata on Microsoft Copilot. |
| `https://www.perplexity.ai/*` | Capture the user’s sent prompts and conversation metadata on Perplexity. |
| `https://brainplug.app/app/*` | Run the bridge that reports the capture count and, when the app asks after the user chooses to add them, passes captures to the web app inside the browser. |
| `https://www.brainplug.app/app/*` | Provide the same local bridge when the app is served at the www address. |
| `http://127.0.0.1/app/*` | Provide the same bridge for a locally served copy of the browser web app, including local browser tests. |
| `http://localhost/app/*` | Provide the same bridge for a locally served copy using the localhost name. |

**Remote code:** No, the extension does not use remote code. All extension scripts
are in the ZIP. Opening the separate web app does not execute its code in the
extension.

**Data usage:** Declare local data handling; do not select “no user data” merely
because there is no upload. Saved fields are `text`, `site`, `conv`, `title` and
`ts`, plus a local pause preference. The text is freeform and is not redacted.
Use the following disclosures, including sensitive information only as content
the user includes in a sent prompt or conversation title:

| Dashboard data type | Answer and scope |
| --- | --- |
| Website content | Yes: the user’s sent composer text and the page title; no AI answers. |
| Personal communications | Yes: the user’s outgoing AI-chat messages. |
| Web history | Yes, limited to the supported AI site, conversation identifier derived from its path, title and timestamp associated with captures; no general browsing history. |
| User activity | Yes: detect Enter/Send and the emptied composer to recognise sent messages; no separate click log or general keystroke history. |
| Personally identifiable information | Yes, if included in the sent text or title; no separate identity profile. |
| Health information | Yes, if included in the sent text or title; no separate health-data source. |
| Financial and payment information | Yes, if included in the sent text or title; no access to payment accounts. |
| Authentication information | Yes, if the user includes it in sent text or a title; no separate access to login forms, authentication cookies or session-token storage. |
| Location | Yes, if included in the sent text or title; no geolocation or IP-location lookup. |

**Data use certifications — check all three:**

- Data is not sold or transferred to third parties. Captures stay in the browser,
  with an in-browser handover to Brainplug’s app and user-requested file export.
  Neither operation uploads captures.
- Data is not used or transferred for purposes unrelated to the extension’s
  single purpose: capturing the user’s writing for Brainplug.
- Data is not used or transferred to determine creditworthiness or for lending.

The separate Python MCP integration is not an extension upload mechanism. If the
user imports captures there and lets an assistant read them, that assistant sends
tool results to its model provider, as explained in the privacy policy.

### Screenshots to prepare — English

Prepare five 1280×800 screenshots, using invented prompts and titles throughout.
Capture the actual UI and avoid real account details. Make a Spanish set with
the same scenes and Spanish browser language; use `?lang=es` for the web app.

1. **Sent prompt and local count:** A supported AI chat with an invented sent
   prompt and the extension popup open, showing a saved-message count and site
   breakdown. Caption: “Your sent prompts, saved in this browser.”
2. **Capture controls:** The popup with existing captures and “Save what I type”
   switched off. Show the export and delete controls. Caption: “Pause capture,
   save a file, or delete your history.”
3. **Add to Brainplug:** The web app showing its saved-message offer and “Add
   them” button before import. Caption: “Add captures inside your browser.”
4. **Map from captures:** A generated Brainplug map made from invented captures,
   with a selected item containing only the user’s prompt text. Caption:
   “Explore your own writing in Brainplug.”
5. **JSON export:** The popup with “Save as a file” and the completed
   `brainplug-capture.json` download visible. Caption: “Keep a file you control.”

## Ficha en español

**Nombre:** Brainplug capture

**Descripción breve:** Guarda localmente los mensajes que envías a ChatGPT, Claude, Gemini, Copilot y Perplexity para Brainplug.

**Categoría:** Productividad → Herramientas (Productivity → Tools)

**Descripción detallada:**

Brainplug capture guarda una copia local de los mensajes que envías en ChatGPT,
Claude, Gemini, Microsoft Copilot y Perplexity para añadir tus escritos a
Brainplug. No lee ni guarda las respuestas de la IA.

Cuando pulsas Intro o Enviar y el cuadro del mensaje se vacía, la extensión
guarda tu texto en el almacenamiento local de extensiones de este navegador.
Cada registro incluye el sitio, el identificador de conversación, el título
disponible de la página y la fecha y hora. Cada captura tiene un límite de
20.000 caracteres. No se conservan los borradores sin enviar.

Abre el panel para ver cuántos mensajes hay guardados, pausar o reanudar la
captura, descargar un archivo JSON o borrar todo lo guardado. El borrado pide
una segunda pulsación. Pausar conserva el historial anterior.

«Crear mi Brainplug» abre https://brainplug.app/app/. La app web ofrece añadir
tus mensajes guardados. Si eliges «Añadirlos», la extensión los entrega a la
página dentro del navegador, sin transferirlos por la red. La app web los
analiza en la pestaña para crear tu mapa. También puedes importar el JSON
descargado en Brainplug, incluida su versión de Python.

La extensión no hace peticiones de red ni sube capturas. No hay cuentas de
Brainplug, cookies, analítica ni publicidad. Los sitios de IA siguen recibiendo
los mensajes que les envías conforme a sus políticas. Cargar la web de Brainplug
hace peticiones normales a su proveedor de alojamiento, GitHub Pages.

Sitios compatibles: chatgpt.com, chat.openai.com, claude.ai, gemini.google.com,
copilot.microsoft.com y www.perplexity.ai. La captura depende de detectar el
envío y el vaciado del cuadro; los cambios en esos sitios pueden afectarla.
Las pruebas automáticas del navegador usan páginas simuladas, no los servicios
reales.

Brainplug es código abierto con licencia MIT. Política de privacidad:
https://brainplug.app/privacy.html. Consultas o errores:
https://github.com/juanmariarodriguez2-png/brainplug/issues.

### Prácticas de privacidad — español

**Finalidad única:** Guardar una copia local de los mensajes que el usuario envía
a los sitios de chat con IA compatibles para que pueda importar sus propios
escritos en Brainplug.

**Justificación de permisos:**

| Permiso | Justificación |
| --- | --- |
| `storage` | Guardar mensajes enviados, metadatos de conversación y el ajuste de pausa en `chrome.storage.local`; leerlos para el panel, la exportación JSON y la importación local en la app web; borrar capturas cuando se solicita. |
| `unlimitedStorage` | Conservar un historial local creciente por encima de la cuota predeterminada de `storage.local` de Chrome, sin subirlo ni descartar mensajes antiguos para ajustarse a esa cuota. El espacio en disco sigue siendo un límite. |

**Justificación del acceso a sitios:** Son patrones de `content_scripts.matches`,
no una lista adicional de `host_permissions`. Todos sirven a la finalidad única.

| Patrón | Justificación |
| --- | --- |
| `https://chatgpt.com/*` | Ejecutar la captura en ChatGPT para detectar texto enviado y conservar identificadores y títulos de conversación. |
| `https://chat.openai.com/*` | Ejecutar la misma captura en la dirección antigua de ChatGPT cuando se use. |
| `https://claude.ai/*` | Capturar los mensajes enviados por el usuario y sus metadatos de conversación en Claude. |
| `https://gemini.google.com/*` | Capturar los mensajes enviados por el usuario y sus metadatos de conversación en Gemini. |
| `https://copilot.microsoft.com/*` | Capturar los mensajes enviados por el usuario y sus metadatos de conversación en Microsoft Copilot. |
| `https://www.perplexity.ai/*` | Capturar los mensajes enviados por el usuario y sus metadatos de conversación en Perplexity. |
| `https://brainplug.app/app/*` | Ejecutar el puente que informa del número de capturas y las entrega a la app web dentro del navegador cuando esta las solicita tras elegir el usuario añadirlas. |
| `https://www.brainplug.app/app/*` | Ofrecer el mismo puente local cuando la app se sirve en la dirección con www. |
| `http://127.0.0.1/app/*` | Ofrecer el mismo puente para una copia local de la app web del navegador, incluidas las pruebas locales. |
| `http://localhost/app/*` | Ofrecer el mismo puente para una copia local servida con el nombre localhost. |

**Código remoto:** No, la extensión no usa código remoto. Todos sus scripts están
en el ZIP. Abrir la app web independiente no ejecuta su código en la extensión.

**Uso de datos:** Declarar el tratamiento local; no marcar «ningún dato de
usuario» por el hecho de que no haya subidas. Los campos guardados son `text`,
`site`, `conv`, `title` y `ts`, además de una preferencia local de pausa. El texto
es libre y no se enmascara. Declarar lo siguiente, incluidos los datos sensibles
solo como contenido que el usuario incorpora a un mensaje enviado o al título:

| Tipo de datos del panel | Respuesta y alcance |
| --- | --- |
| Contenido de sitios web | Sí: texto enviado desde el cuadro y título de la página; sin respuestas de la IA. |
| Comunicaciones personales | Sí: mensajes salientes del usuario en chats con IA. |
| Historial web | Sí, limitado al sitio de IA compatible, identificador de conversación derivado de su ruta, título y fecha y hora asociados a las capturas; sin historial general de navegación. |
| Actividad del usuario | Sí: detectar Intro/Enviar y el vaciado del cuadro para reconocer envíos; sin registro separado de clics ni historial general de pulsaciones. |
| Información de identificación personal | Sí, si se incluye en el texto enviado o título; sin perfil de identidad separado. |
| Información de salud | Sí, si se incluye en el texto enviado o título; sin otra fuente de datos sanitarios. |
| Información financiera y de pagos | Sí, si se incluye en el texto enviado o título; sin acceso a cuentas de pago. |
| Información de autenticación | Sí, si el usuario la incluye en el texto enviado o título; sin acceso separado a formularios de inicio de sesión, cookies de autenticación ni almacenamiento de tokens de sesión. |
| Ubicación | Sí, si se incluye en el texto enviado o título; sin geolocalización ni búsqueda de ubicación por IP. |

**Certificaciones de uso de datos — marcar las tres:**

- Los datos no se venden ni transfieren a terceros. Las capturas permanecen en
  el navegador, con entrega interna a la app de Brainplug y exportación a archivo
  solicitada por el usuario. Ninguna de esas operaciones sube capturas.
- Los datos no se usan ni transfieren para fines ajenos a la finalidad única de
  la extensión: capturar los escritos del usuario para Brainplug.
- Los datos no se usan ni transfieren para determinar la solvencia ni conceder
  préstamos.

La integración MCP de Python es independiente y no es un mecanismo de subida de
la extensión. Si el usuario importa allí capturas y deja que un asistente las
lea, ese asistente envía los resultados al proveedor de su modelo, como explica
la política de privacidad.

### Capturas de pantalla que preparar — español

Preparar cinco capturas de 1280×800, con mensajes y títulos inventados. Mostrar
la interfaz real y evitar datos de cuentas reales. Usar el navegador en español
y `?lang=es` en la app web. Preparar las mismas escenas para la ficha inglesa.

1. **Mensaje enviado y contador local:** Chat de IA compatible con un mensaje
   inventado enviado y el panel abierto, mostrando contador y desglose por sitio.
   Texto: «Tus mensajes enviados, guardados en este navegador».
2. **Controles de captura:** Panel con capturas existentes y «Guardar lo que
   escribo» desactivado. Mostrar exportación y borrado. Texto: «Pausa la captura,
   guarda un archivo o borra tu historial».
3. **Añadir a Brainplug:** App web con la oferta de mensajes guardados y el botón
   «Añadirlos» antes de importar. Texto: «Añade capturas dentro del navegador».
4. **Mapa de capturas:** Mapa creado con capturas inventadas, con un elemento
   seleccionado que contenga solo el texto del usuario. Texto: «Explora tus
   propios escritos en Brainplug».
5. **Exportación JSON:** Panel con «Guardar archivo» y la descarga terminada de
   `brainplug-capture.json` visible. Texto: «Conserva un archivo que tú controlas».

## Dashboard references

Google requires disclosure of local handling too; see its
[user-data FAQ](https://developer.chrome.com/docs/webstore/program-policies/user-data-faq).
The permission, purpose, remote-code and certification fields follow the
[privacy-fields guide](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy).
Screenshot preparation follows the
[listing guide](https://developer.chrome.com/docs/webstore/cws-dashboard-listing).
