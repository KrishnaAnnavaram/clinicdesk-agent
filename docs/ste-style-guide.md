# ASD-STE100 Simplified Technical English: the text standard

The `README.md` of clinicdesk-agent and this guide use these rules. Section 1 and Section 2 are the
general rules. Section 3 is the **project vocabulary**: the technical names and the technical verbs
of clinicdesk-agent, each with one meaning. If you change the README, use these rules and these terms.

## 1. Rules for the text

### Words

1. Use one word for one meaning, and one meaning for one word. Do not use synonyms for variety.
2. Use a word only as one part of speech. For example, "test" is a noun or a verb, "check" is a verb.
3. Do not use phrasal verbs (`set up`, `carry out`, `find out`, `pick up`, `look up`, `come up with`).
   Use one verb: "prepare", "do", "find", "get", "make".
4. Do not use an "-ing" form as a noun or an adjective ("the running job", "after indexing").
   Exception: a technical name, a file name, a command or a status value.
5. Do not use contractions (`don't`, `it's`, `can't`). Do not use slang or idioms
   (`out of the box`, `under the hood`, `at a glance`, `gotcha`, `bells and whistles`).
6. Do not use `and/or`. Write "A, B or both".
7. Do not use `should`, `could`, `would` or `may` for instructions. Use "must" for a rule, the
   imperative for a step and "can" for a possibility.
8. Keep the articles "a", "an" and "the" in sentences.
9. Do not make a noun cluster of more than three words. A technical name is one word.

### Sentences

1. A procedural sentence (an instruction) has a maximum of **20 words**.
2. A descriptive sentence has a maximum of **25 words**.
3. Write one instruction in one sentence.
4. Use the imperative for an instruction: "Run the tests." Not `The tests should be run.`
5. Use the active voice. Use the passive voice only when the agent of the action is not important.
6. Use only the simple present, the simple past and the simple future.
7. Put a condition before the instruction: "If the index is stale, build it again."
8. Do not use semicolons in sentences. Write two sentences.

### Paragraphs, notes and warnings

1. A paragraph has one topic and a maximum of **6 sentences**. Start with the topic sentence.
2. A warning or a caution starts with a clear command. Then it gives the reason.
3. A note gives information. It does not give an instruction.
4. Use a vertical list for a sequence or a set of conditions. Each item of a numbered procedure is one step.

### Tables, headings and diagrams

1. A table cell can be a short phrase. If a cell has a sentence, the sentence obeys the rules.
2. A heading is a noun phrase ("The cost model") or an imperative ("Run the demo").
   Do not start a heading with an "-ing" form.
3. A diagram label is a short phrase. Use the same terms as the text.

### What STE does not change

Code, commands, file names, paths, field names, environment variables, status values, enum values,
product names and URLs stay exactly as they are. They are technical names. Put them in backticks.

## 2. General words to replace

| Do not use | Use |
|---|---|
| utilize, leverage | use |
| in order to | to |
| set up | prepare, install, configure |
| carry out, perform | do |
| make sure, ensure | make sure (allowed), or "check that" |
| a lot of, lots of | many, much |
| e.g., i.e. | for example, that is |
| should (instruction) | must (rule) / imperative (step) |
| might, may (possibility) | can |
| very, really, just, simply, easily | (delete) |
| seamless, robust, powerful, blazing | (delete or give a measured fact) |


## 3. Project vocabulary

These terms have one meaning in the README and in this guide. The "Do not use" column lists the
synonyms that the documents do not use for the same meaning.

### 3.1 Technical names (nouns)

| Term | Meaning | Do not use |
|---|---|---|
| **assistant** | The complete clinicdesk-agent program that talks to a patient | bot, chatbot, agent (alone), AI |
| **patient** | The person who signs in and sends messages | user, client, customer |
| **handle** | The login name of a patient (3 to 32 characters) | username, user name, login, account name |
| **passcode** | The secret that a patient gives at sign-in (minimum 6 characters) | password, PIN, secret |
| **sign-in** | The check of a handle and a passcode against the `patients` table | login, logon, authentication (in prose) |
| **session** | The state of one conversation: patient id, handle, history and proposal | context, state object |
| **conversation** | The live exchange of messages between one patient and the assistant | chat session, thread |
| **message** | One text that the patient sends | query, prompt, input, request (for text) |
| **reply** | One text that the assistant sends back | response, answer, output |
| **reply kind** | The label on a reply: `answer`, `emergency`, `refusal`, `confirm`, `done` or `error` | reply type (in prose), category |
| **model** | The chat model that reads the conversation and sends tool calls | LLM (in prose), AI, brain |
| **offline model** | The rule-based model `RuleBasedChatModel`. It needs no network and no key | mock, fake, stub, dummy model |
| **hosted model** | A model behind an OpenAI-compatible chat API, remote or local | cloud model, real model, online model |
| **provider** | The value of `CLINICDESK_LLM_PROVIDER`: `offline` or `openai` | backend, vendor, engine |
| **tool** | One of the eight typed functions in `TOOL_SPECS` that the model can call | function, action, skill, command |
| **tool call** | One request from the model to run one tool with arguments | function call, invocation |
| **tool result** | The JSON object that a tool gives back to the model | tool output, tool response |
| **read tool** | A tool that only reads data: `triage_symptoms`, `list_specialties`, `find_doctors`, `search_slots`, `list_my_appointments` | query tool, lookup tool |
| **proposal tool** | A tool that only stores a proposal: `request_booking`, `request_cancellation`, `request_reschedule` | write tool, action tool |
| **proposal** | The one pending change in a session (`PendingAction`): book, cancel or reschedule | draft, pending request, suggestion |
| **confirmation** | An explicit "yes" (or the Confirm button) that applies the proposal | approval, consent, acceptance |
| **orchestrator** | The class `Orchestrator`, which runs the safety screen, the confirmation step and the model loop | agent loop, controller, runner |
| **toolbox** | The class `Toolbox`, which validates tool calls and runs the tool handlers | tool layer, tool registry |
| **booking service** | The class `BookingService`, the only code that writes bookings | scheduler, booking engine |
| **step** | One call to the model inside the loop for one message | turn (for model calls), iteration, round trip |
| **step limit** | The maximum number of steps for one message (`CLINICDESK_MAX_TOOL_STEPS`) | max iterations, loop limit |
| **safety screen** | The code checks for red flags and advice requests before the model runs | filter, guardrail, moderation |
| **red flag** | A text pattern for a possible emergency, for example chest pain | alarm, trigger, emergency keyword |
| **emergency reply** | The fixed reply that tells the patient to call the emergency number | emergency message (in prose), alert |
| **advice request** | A message that asks for a diagnosis, a medicine or a dose | medical question, clinical query |
| **refusal** | The fixed reply to an advice request | rejection, denial |
| **disclaimer** | The fixed "not medical advice" text that follows each triage reply | warning text, notice |
| **triage** | The rule-based choice of one specialty from symptom words. It is not a diagnosis | diagnosis, assessment, classification |
| **specialty** | One of the ten clinical areas, for example `Cardiology` | department, speciality, service |
| **doctor** | One row in the `doctors` table: a name and one specialty | clinician (for a table row), physician, provider |
| **slot** | One published start time of one doctor, in the `slots` table | time slot, opening, availability |
| **booking** | One row in the `bookings` table that links one patient to one slot | appointment (in prose), reservation |
| **active booking** | A booking with the status `active` | live booking, open booking |
| **upcoming booking** | An active booking with a start time after the clock time | future appointment, next appointment |
| **idempotency key** | A unique text that makes a retried `book` return the first booking | request id, dedup key |
| **clinic time** | The wall-clock time in `CLINICDESK_TIMEZONE`, stored without an offset | local time, server time |
| **date phrase** | The words that a patient uses for a day or a range, for example "next week" | date string, date text |
| **part of day** | `morning` (06:00 to 12:00), `afternoon` (12:00 to 17:00) or `evening` (17:00 to 21:00) | time window, period |
| **invariant** | A database rule that the evaluation harness checks after each dialogue | constraint (for the harness check), assertion |
| **dialogue** | One scripted conversation in `dialogues.json` with expected results | scenario, test case, script |
| **evaluation harness** | The module `evaluation/harness.py` that runs all dialogues and gives a score | evaluator, benchmark, test runner |
| **demo database** | The SQLite file that `clinicdesk init-db` makes with synthetic data | sample data, fixture database |
| **demo patient** | A synthetic patient `demo-patient-a` to `demo-patient-e` that holds pre-booked slots | test user, dummy patient |

### 3.2 Technical verbs

| Verb | Meaning |
|---|---|
| **book** | Make an active booking for one slot |
| **cancel** | Set an active booking to `cancelled` and release its slot |
| **reschedule** | Move an active booking to a different slot in one transaction |
| **propose** | Store one proposal in the session, with no database write |
| **confirm** | Apply the proposal after an explicit "yes" from the patient |
| **decline** | Delete the proposal after an explicit "no" from the patient |
| **claim** | Set `is_booked = 1` on a free slot with a conditional `UPDATE` |
| **release** | Set `is_booked = 0` on a slot after a cancel or a reschedule |
| **screen** | Compare a message with the red-flag and advice patterns |
| **validate** | Compare tool-call arguments with the tool schema and reject bad values |
| **resolve** | Change a date phrase into a start date and an end date in clinic time |
| **seed** | Delete the demo data and write new synthetic doctors, slots and bookings |
| **trim** | Remove the oldest messages from the session history at a patient message |
| **register** | Add a new handle and a passcode hash to the `patients` table |
