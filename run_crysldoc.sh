#!/usr/bin/env bash
set -euo pipefail

export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"

MAIN_CLASS="de.upb.docgen.DocumentGeneratorMain"
VM_OPTS="-Dfile.encoding=UTF-8"
PROGRAM_ARGS=(
  --FTLtemplatesPath src/main/resources/FTLTemplates
  --reportPath Output
  --llm=on
  --llm-backend=openai
)

mvn -q clean compile

CP="$(mvn -q dependency:build-classpath -Dmdep.outputFile=/dev/stdout)"
CP="target/classes:${CP}"

java ${VM_OPTS} -cp "${CP}" "${MAIN_CLASS}" "${PROGRAM_ARGS[@]}"