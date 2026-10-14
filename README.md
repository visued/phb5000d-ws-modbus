# PHB5000D-WS — leitura local via Modbus TCP

Engenharia reversa do inversor **PHB Solar PHB5000D-WS** (linha D-WS, monofásico 5 kW,
2 MPPT) para ler a telemetria **direto na rede local**, sem depender da nuvem do Solar Portal.

Levantamento feito em **2026-10-14**, entre 11:00 e 11:30, com o inversor gerando ~4 kW.

## TL;DR

```bash
python3 phb_reader.py 192.168.18.138          # JSON com potência, energia, PV, rede...
python3 phb_reader.py 192.168.18.138 --watch 30
```

- Modbus TCP na **porta 502**, **somente função 03** (Read Holding Registers).
- A telemetria fica em **30100–30199**. Os campos principais são:
  potência CA `30127-30128`, energia do dia `30144`, energia total `30145-30146`.
- Faça **leituras em bloco** dentro das tabelas conhecidas, use **uma conexão por ciclo** e mantenha
  **≥ 10 s entre ciclos**. Detalhes em [Comportamento do módulo](#comportamento-do-módulo-importante).

`phb_reader.py` usa só a biblioteca padrão do Python (3.8+) e **nunca escreve** no inversor.

---

## Equipamento e rede

| Item | Valor |
|---|---|
| Inversor | PHB5000D-WS (lido do registrador 40173) |
| Nº de série | `25000DSCXXXXXXXX` (registradores 30004–30011; últimos 8 chars omitidos nesta doc) |
| Peça/firmware | `410-02065-05` (registradores 30221–30226; significado exato não confirmado) |
| IP na LAN | `192.168.18.138` (DHCP do roteador 192.168.18.1, ligado por cabo RJ45) |
| MAC | `08:b6:1f:xx:xx:xx`. O OUI 08:B6:1F é da **Espressif**, então o módulo de comunicação é um ESP32 |
| Portas abertas | **só a 502/TCP** (Modbus TCP). A porta 80 não responde pela LAN |
| App / nuvem | Solar Portal (app) e `www.phbsolar.com.br` (portal web). A leitura local não interfere neles |

Segundo o manual, o inversor tem RS485 (Modbus RTU, **9600 bps**, sem paridade), USB-Serial e um slot
para o módulo de comunicação. O módulo encaixado atua como **gateway Modbus TCP → RS485**.

## Comportamento do módulo (importante)

Tudo o que segue foi observado na prática:

1. **O ID de escravo (unit id) é ignorado.** IDs 0, 1, 2, 3, 247 e 255 devolvem os mesmos dados.
   Use `1`.
2. **Só a função 03 funciona.** A função 04 (Input Registers) não recebe resposta em nenhum endereço testado.
3. **Leitura fora de tabela válida não recebe resposta.** Não há exceção Modbus, só silêncio.
   Um bloco que começa num endereço inválido ou atravessa um buraco também fica sem resposta.
   Por exemplo, ler 0–49 funciona e ler a partir de 16 não. Leia sempre os blocos de `BLOCKS` em `phb_reader.py`.
4. **Pedido inválido trava a fila por ~1 s.** O gateway fica esperando o inversor na RS485, e os pedidos
   seguintes atrasam junto. Por isso a varredura às cegas é lenta e o mapeamento registrador a registrador
   **se desalinha**: um mapeador desses chegou a mostrar a potência em 30127 quando ela fica em 30127–30128.
   Confie só em leitura de bloco.
5. **O ESP tem poucos sockets.** Depois de várias reconexões em sequência rápida, o módulo **parou de
   aceitar conexões** por alguns segundos e depois voltou sozinho. Abra uma conexão por ciclo, leia
   tudo nela e feche. Deixe pausas de ~200 ms entre blocos e ≥ 10 s entre ciclos. O módulo também envia
   dados para a nuvem, então não o sobrecarregue.
6. Latência típica de uma leitura válida: **20–30 ms**.
7. `0xFFFF` = **campo não usado** neste modelo (ex.: fases B/C, MPPTs extras).

## Mapa de registradores (função 03)

Confiança:
- **Alta**: o valor fecha com outra grandeza (ex.: V×I ≈ W) ou com o relógio real.
- **Média**: unidade e ordem de grandeza plausíveis, mas sem verificação cruzada.
- **Baixa**: palpite.

### Telemetria — tabela 30100–30199 (bloco `30100, 100`)

| Reg. | Tipo | Escala | Campo | Exemplo (11:28) | Confiança / evidência |
|---|---|---|---|---|---|
| 30100 | u8+u8 | — | ano (−2000) / mês | `0x1A0A` → 26/10 | Alta: bate com a data real |
| 30101 | u8+u8 | — | dia / hora | `0x0E0B` → 14/11 | Alta |
| 30102 | u8+u8 | — | minuto / segundo | `0x1C0A` → 28:10 | Alta: avançou 1:32 entre leituras feitas com 1:31 de intervalo |
| 30103 | u16 | 0,1 V | PV1 tensão (MPPT1) | 2329 → 232,9 V | Alta |
| 30104 | u16 | 0,1 A | PV1 corrente | 118 → 11,8 A | Alta |
| 30105 | u16 | 0,1 V | PV2 tensão (MPPT2) | 1182 → 118,2 V | Alta |
| 30106 | u16 | 0,1 A | PV2 corrente | 122 → 12,2 A | Alta: PV1+PV2 ≈ 4190 W CC vs 4026 W CA (η ≈ 96 %) |
| 30107–30108 | u16 | 0,1 | PV3 tensão/corrente | 0 | Média: não existe no 5000D-WS |
| 30109–30117 | — | — | PV4+ (não usado) | `0xFFFF` | — |
| 30118 | u16 | 0,1 V | Tensão CA fase A | 2283 → 228,3 V | Alta |
| 30119–30120 | — | — | Tensão fases B/C | `0xFFFF` | Alta: monofásico |
| 30121 | u16 | 0,1 A | Corrente CA fase A | 177 → 17,7 A | Alta: 228,3 × 17,7 ≈ 4041 VA |
| 30124 | u16 | 0,01 Hz | Frequência | 6001 → 60,01 Hz | Alta |
| **30127–30128** | **s32** | **1 W** | **Potência ativa CA** | `0000 0FBA` → **4026 W** | Alta |
| 30129 | u16 | — | ? | 1 | Desconhecido |
| 30130–30132 | — | — | ? (zeros; talvez Q em 32 bits) | 0 | Baixa |
| 30133–30134 | s32 | 1 VA | Potência aparente | `0000 0FDF` → 4063 VA | Média: ≈ V×I dentro do arredondamento de 0,1 A |
| 30136 | s16 | 1 var | Potência reativa | `0xFFFE` → −2 var | Média |
| 30139 | u16 | 0,001 | Fator de potência | 999 → 0,999 | Média–alta |
| 30141 | s16 | 0,1 °C | Temperatura 1 (interna?) | 639 → 63,9 °C | Média |
| 30142 | s16 | 0,1 °C | Temperatura 2 (dissipador/módulo?) | 738 → 73,8 °C | Média: subiu com a carga |
| **30144** | **u16** | **0,1 kWh** | **Energia do dia** | 115 → **11,5 kWh** | Alta: +1 (0,1 kWh) em 90 s a ~4 kW (esperado 0,10 kWh) |
| **30145–30146** | **u32** | **0,1 kWh** | **Energia total** | `0002 24D1` → **14 049,7 kWh** | Alta: +0,1 kWh junto com a do dia |
| 30147–30148 | u32 | 1 h | Horas de operação (total) | 7390 h | Média: ~2 anos × ~10 h/dia |
| 30149 | u16 | — | ? | 16 | Desconhecido |
| 30163 | u16 | 0,1 V | Tensão do barramento CC | 3581 → 358,1 V | Média: típico de inversor 220 V |
| 30167 | u16 | 0,1 ? | ? (talvez outra temperatura) | 735 | Baixa |
| 30168–30169 | u32 | — | ? (oscila: 5484 → 5479) | 5479 | Desconhecido |
| 30172–30173 | u32 | — | ? (estável; talvez resistência de isolação) | 6553 | Baixa |
| 30175 | u16 | 0,1 A | Corrente string 1 | 118 → 11,8 A | Média–alta: = PV1 |
| 30176 | u16 | 0,1 A | Corrente string 2 | 122 → 12,2 A | Média–alta: = PV2 |

### Identificação / estado — tabelas 30001–30016, 30034–30084, 30200–30229

| Reg. | Tipo | Campo | Valor | Confiança |
|---|---|---|---|---|
| 30001–30002 | u16 | ? | 0, 0 | Desconhecido |
| 30003 | u16 | ? | 1 | Desconhecido |
| 30004–30011 | ASCII (16 chars) | Número de série | `25000DSCXXXXXXXX` | Alta |
| 30034 | u16 | Estado de operação (provável) | 6 (gerando) | Baixa: confirmar à noite, quando deve mudar |
| 30035–30036 | u16 | ? | 5, 5 | Desconhecido |
| 30037 | u16 | ? | 6009 | Desconhecido |
| 30038 | u16 | ? | 45 | Desconhecido |
| 30039 | u16 | ? | 8 | Desconhecido |
| 30040–30084 | u16 | quase tudo 0, exceto 30064 = 4 (códigos de falha/alarme?) | — | Baixa |
| 30221–30226 | ASCII (12 chars) | Peça/versão de firmware | `410-02065-05` | Média |

### Configuração / módulo — tabelas 0–49 e 40000+

| Reg. | Conteúdo | Observação |
|---|---|---|
| 0 | `2` (1–49 = `0xFFFF`) | Desconhecido |
| 40000–40023 | Três strings de 16 chars, todas `12345678` | **Senhas padrão** do módulo (o guia PHB cita `12345678` como senha padrão do Wi-Fi). Ver Segurança |
| 40024–40031 | `0xFFFF` | — |
| 40144–40153 | `00F7 0030 2580 0000 0000 0001 0000 FFFF…` | Provável config. de comunicação: 0xF7 = 247 (endereço?), 0x2580 = **9600** (baud) |
| 40173–40188 | ASCII `PHB5000D-WS` | Modelo. Alta |
| 40300 | `0x3235` ("25…") | Tabela não mapeada (provavelmente começa com o nº de série) |
| 42000 | `1` | Tabela não mapeada |

Sem resposta (testado): função 04 em todos os endereços; função 03 em 1, 0x0010–0x0600, 0x1000–0xC000
(passo 0x1000), 3000, 3500, 4000, 5000, 10000, 11000, 20000, 30000, 31001, 31301, 32000, 33000, 35100,
36000, 40100, 40200, 41000, 43000–45000, 50000. **Uma busca negativa vale só para o endereço de início
testado**: uma tabela pode existir começando em outro endereço próximo.

Amostras brutas completas: [`amostras/`](amostras/), duas leituras com 90 s de intervalo
(registradores 30008–30011 do número de série substituídos por `0x5858` = "XX").

## Como foi descoberto (metodologia)

1. **Varredura da LAN** (`192.168.18.0/24`) por portas típicas de inversor/datalogger
   (80, 502, 8899, 8080, …). Só o `192.168.18.138` tinha a **502** aberta. O MAC é da Espressif.
2. **Sondagem somente leitura** com função 03/04. As respostas idênticas para qualquer unit id
   mostraram que o módulo é um gateway. A leitura de `40173` devolveu `PHB5000D-WS`, o que confirmou o alvo.
3. **Documentação PHB:** o manual da linha D-WS cita RS485 Modbus 9600 bps, opções de menu
   "Config. Modbus" e "Config. Sunspec", e o app Solar Portal. O guia de Wi-Fi traz o AP `Solar-WiFi`,
   o IP `10.10.100.253`, o login `admin/admin` e a senha padrão `12345678`. Essa senha explicou as
   strings em 40000.
4. **Sondagem dos endereços iniciais mais comuns** em mapas Modbus de fabricantes OEM. Responderam 30001,
   40300 e 42000.
5. **Mapeamento fino da faixa 30000** e **identificação dos campos por coerência física**
   (V×I = W, relógio = hora atual).
6. **Diff entre dois snapshots** com 90 s de intervalo. Os únicos contadores que subiram exatamente
   0,1 kWh foram 30144 e 30145–30146, o que define energia do dia e energia total.

O REA (ferramentas de engenharia reversa) não foi necessário. O protocolo é Modbus puro e respondeu às
leituras diretas. Ele ainda serve para fechar as lacunas abaixo, analisando o APK do Solar Portal ou uma
captura (pcap) do tráfego do módulo.

## Segurança

- Os registradores 40000–40023 parecem guardar as **senhas do módulo** (de fábrica, `12345678`) e podem
  ser lidos por qualquer aparelho da LAN. Com a senha padrão, qualquer pessoa no alcance do AP Wi-Fi
  `Solar-WiFi…` entra nele e chega à página de configuração (`admin/admin` por padrão).
  **Troque as senhas padrão** pela página do módulo ou pelo app.
- O Modbus TCP na 502 **não tem autenticação**. Qualquer aparelho da LAN lê o inversor e,
  possivelmente, escreve nele. Não exponha a porta 502 para a internet (port forwarding/UPnP).
- `phb_reader.py` só envia a função 03. Não adicione escrita (06/16) sem o mapa oficial: um registrador
  errado pode mudar a norma de rede, o limite de potência etc.

## Pendências / próximos passos

- [ ] Confirmar **30034 = estado** lendo à noite e no amanhecer (inversor desligado → conectando → gerando).
- [ ] Identificar 30129, 30149, 30168–30169, 30172–30173, 30035–30039 e 30064.
- [ ] Mapear as tabelas 40300+ e 42000+.
- [ ] Testar se ativar "Config. Sunspec" no display expõe o mapa SunSpec padrão (`SunS` em 40000).
  **Atenção:** pode mudar o que o módulo/nuvem enxergam. Testar com cuidado.
- [ ] Pedir à PHB o "protocolo Modbus da linha D-WS" para confirmar escalas e nomes.
- [ ] Conferir **energia do dia/total** com o display ou o app em um mesmo horário.

## Uso em outros projetos

```python
from phb_reader import read_inverter
d = read_inverter("192.168.18.138")
print(d["ac_w"], "W agora |", d["energy_today_kwh"], "kWh hoje |", d["energy_total_kwh"], "kWh total")
```

Exemplo de saída (`python3 phb_reader.py 192.168.18.138`, 2026-10-14 11:30):

```json
{"model": "PHB5000D-WS", "serial": "25000DSCXXXXXXXX", "inverter_time": "2026-10-14T11:30:10",
 "pv": [{"mppt": 1, "v": 232.7, "a": 11.8, "w": 2746}, {"mppt": 2, "v": 117.4, "a": 12.2, "w": 1432}],
 "pv_w": 4178, "ac_v": 228.4, "ac_a": 17.6, "ac_hz": 59.99, "ac_w": 4011, "ac_va": 4047, "ac_var": 0,
 "pf": 0.999, "temp1_c": 64.0, "temp2_c": 73.9, "energy_today_kwh": 11.6, "energy_total_kwh": 14049.8,
 "hours_total": 7390, "bus_v": 358.2, "string_a": [11.8, 12.2], "status_raw": 6,
 "fw_part": "410-02065-05", "read_at": "2026-10-14T11:30:20"}
```

Ideias: Home Assistant (integração `modbus` com `type: tcp`, `input_type: holding`, `slave: 1`, um
sensor por campo da tabela acima), Grafana/InfluxDB, alertas de queda de geração e o smart-clock
(endpoint `/solar` do coletor em [visued/smart-clock](https://github.com/visued/smart-clock)).

## Fontes

- [Manual do usuário — linha D-WS (PHB, v1.4)](https://www.plataformaphbsolar.com.br/imagemsite/inversores/manual/linha_d-ws.pdf)
- [Datasheet PHB3100/5000D-WS](https://www.plataformaphbsolar.com.br/imagemsite/inversores/datasheet/phb3100_5000d_ws_afci.pdf)
- [Guia rápido de configuração Wi-Fi (PHB, rev 2.0)](https://www.energiasolarphb.com.br/wp-content/uploads/2021/04/Guia-Rapido-Configuracao-Wi-Fi_rev2.0.pdf)
- [Guia PHB Web Solar Portal](https://www.energiasolarphb.com.br/wp-content/uploads/2021/04/Guia-PHB-Web-Solar-Portal-PT-BR-Completo.pdf)
- [Tutoriais PHB Solar](https://www.energiasolarphb.com.br/tutoriais/)
