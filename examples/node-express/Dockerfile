FROM node:22-alpine
WORKDIR /app

COPY examples/node-express/package.json .
RUN npm install

COPY examples/node-express/app.js .
EXPOSE 8001
CMD ["node", "app.js"]
