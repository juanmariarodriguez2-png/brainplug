"""Stop words for English and Spanish chats, plus words that are typical of
how people talk *to* an AI but say nothing about the topic."""

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

SPANISH = """
a al algo algunas algunos ante antes aquel aquella aquellas aquello aquellos aqui aquí
asi así aun aún bien cada casi como cómo con contra cual cuál cuales cuando cuándo cuanto
de del desde donde dónde dos el él ella ellas ello ellos en entre era eran es esa esas ese
eso esos esta está estaba estaban estamos estan están estar estas este esto estos estoy fue
fueron ha habia había han hasta hay he la las le les lo los mas más me mi mis mucho muchos
muy nada ni no nos nosotros o os otra otras otro otros para pero poco por porque que qué
quien quién se ser si sí sido sin sobre son su sus tambien también tan tanto te tener tengo
ti tiene tienen todo todos tu tú tus un una unas uno unos usted ustedes va vamos van vez y
ya yo eres soy hace hacer hago puede puedes puedo pues sea solo sólo ser será sería tenia
tenía mio mío mia mía tuyo suyo nuestra nuestro vosotros esto oye vale ok okay
""".split()

CHAT_FILLER = """
explain explica explicame explícame help ayuda ayudame ayúdame example ejemplo ejemplos
question pregunta quick rapido rápido best mejor way manera forma understand entender
trying intentando sure gracias thanks thank please porfa porfavor favor want quiero
quieres need necesito give dame make hazme haz tell dime know saber sabes hola hello hi
good bueno buena better pasa get got use usar using like como can could would should
does did do done think creo really realmente something algo thing cosa cosas también
also just now ahora aqui here there alli allí yes no sí claro okay vale mira look see
ver new nuevo nueva one dos three tres first primero last último vs versus etc
http https www com org html saludos regards cheers dear estimado estimada hey abrazo
buenas buenos dias días tardes noches kind best atentamente cordial cordialmente un
una note notes nota notas todo page página pagina re fwd
""".split()

STOP_WORDS = sorted(set(ENGLISH_STOP_WORDS) | set(SPANISH) | set(CHAT_FILLER))
