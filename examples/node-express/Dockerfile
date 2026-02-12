FROM node:22-alpine

# Build the local Argus Node SDK
COPY packages/sdk-node/ /tmp/sdk-node/
WORKDIR /tmp/sdk-node
RUN npm install && npm run build

# Install app dependencies (includes @argus/node as file:/tmp/sdk-node)
WORKDIR /app
COPY examples/node-express/package.json .
RUN npm install

COPY examples/node-express/app.js .
EXPOSE 8001
CMD ["node", "app.js"]
